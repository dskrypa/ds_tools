"""
Utilities for copying files with a progress indicator

Note: The simplest way to copy data between 2 file-like objects:

    with input_obj as f_in:
        with output_obj as f_out:
            shutil.copyfileobj(f_in, f_out)


:author: Doug Skrypa
"""

import errno
import logging
import os
import sys
from concurrent import futures
from itertools import cycle
from pathlib import Path
from threading import Event
from time import monotonic
from typing import Union, BinaryIO, Optional

from tz_aware_dt.utils import format_duration
from ..output.formatting import readable_bytes
from .hash import sha512sum
from .paths import is_on_local_device, get_disk_partition

__all__ = ['copy_file']
log = logging.getLogger(__name__)

_WINDOWS = os.name == 'nt'
_USE_CP_SENDFILE = hasattr(os, 'sendfile') and sys.platform.startswith('linux')
MAX_BUF_SIZE = 2 ** 30 if sys.maxsize < 2 ** 32 else None  # 1 GB cap on 32-bit architectures
DEFAULT_BUF_SIZE = 8388608  # 8 MB
# DEFAULT_BUF_SIZE = 10485760  # 10 MB


class FileCopy:
    def __init__(
        self,
        src_path: Union[str, Path],
        dst_path: Union[str, Path],
        buf_size: Optional[int] = None,
        fast: bool = True,
        reuse_buf: bool = True,
    ):
        self.src_path = Path(src_path).expanduser() if not isinstance(src_path, Path) else src_path
        self.dst_path = Path(dst_path).expanduser() if not isinstance(dst_path, Path) else dst_path
        if self.dst_path.exists():
            raise FileExistsError(f'File already exists: {dst_path}')
        if not self.dst_path.parent.exists():
            self.dst_path.parent.mkdir(parents=True)
        self.copied = 0
        self.finished = Event()
        self.src_size = self.src_path.stat().st_size
        self.buf_size = buf_size
        self.fast = fast
        self.reuse_buf = reuse_buf

    @property
    def buf_size(self) -> int:
        return self._block_size or DEFAULT_BUF_SIZE

    @buf_size.setter
    def buf_size(self, value: Optional[int]):
        if value:
            self._block_size = MAX_BUF_SIZE if MAX_BUF_SIZE and value > MAX_BUF_SIZE else value
        else:
            self._block_size = None

    @property
    def sendfile_buf_size(self):
        if self._block_size:
            return self._block_size
        elif self.src_size <= DEFAULT_BUF_SIZE:
            return DEFAULT_BUF_SIZE
        elif not is_on_local_device(self.src_path):
            return 2 ** 25  # 32 MB  # This seems to be the fastest
        else:
            return 2 ** 26  # 64 MB
            # return 2 ** 27  # 128 MB  # shutil default on OSError for stat of src file
            # return MAX_BUF_SIZE if MAX_BUF_SIZE and self.src_size > MAX_BUF_SIZE else self.src_size

    @classmethod
    def copy(
        cls,
        src_path: Union[str, Path],
        dst_path: Union[str, Path],
        verify: bool = False,
        buf_size: Optional[int] = None,
        fast: bool = True,
        reuse_buf: bool = True,
    ):
        """
        :param Path src_path: Source path
        :param Path dst_path: Destination path
        :param bool verify: Verify integrity of copied file
        :param int buf_size: Number of bytes to read at a time (default: 8 MB)
        :param bool fast: Allow faster copy methods to be used when supported
        :param bool reuse_buf: When not using os.sendfile, always readinto a buffer rather than obtaining a new bytes
          object for each read
        """
        cls(src_path, dst_path, buf_size, fast, reuse_buf).run(verify)

    def run(self, verify: bool = False):
        with futures.ThreadPoolExecutor(max_workers=2) as executor:
            _futures = [executor.submit(self.copy_file), executor.submit(self.show_progress)]
            try:
                for future in futures.as_completed(_futures):
                    future.result()
            except BaseException:  # Inside the as_completed loop
                self.finished.set()
                print()
                if self.dst_path.exists():
                    log.warning(f'Deleting incomplete {self.dst_path}')
                    self.dst_path.unlink()
                raise

        if verify:
            self.verify()

    def show_progress(self):
        # Run this in a separate thread so that the spinner can move even if a chunk takes longer than 0.3s to process
        src_size = self.src_path.stat().st_size
        pct, elapsed, rate = 0, 0, readable_bytes(0)
        spinner = cycle('|/-\\')
        name = self.src_path.name
        fmt = '\r{{:11}} {{:>9}}/s {{:6.2%}} [{{:10}}] [{}] {{}}'.format(readable_bytes(src_size))
        is_finished, wait = self.finished.is_set, self.finished.wait
        start = monotonic()

        dst_fs = get_disk_partition(self.dst_path).fstype
        if not _WINDOWS and dst_fs == 'nfs':
            while not is_finished() and pct < .9:
                elapsed = monotonic() - start
                rate = readable_bytes((self.copied / elapsed) if elapsed else 0)
                pct_chars = int(pct * 10)
                bar = '{}{}{}'.format('=' * pct_chars, next(spinner), ' ' * (9 - pct_chars))
                print(fmt.format(format_duration(int(elapsed)), rate, pct, bar, name), end='' if pct < 1 else '\n')
                wait(0.3)
                pct = self.copied / src_size

            while not is_finished() and (remaining := get_writeback_size()):
                elapsed = monotonic() - start
                copied = src_size - remaining  # noqa
                pct = copied / src_size
                rate = readable_bytes((copied / elapsed) if elapsed else 0)
                pct_chars = int(pct * 10)
                bar = '{}{}{}'.format('=' * pct_chars, next(spinner), ' ' * (9 - pct_chars))
                print(fmt.format(format_duration(int(elapsed)), rate, pct, bar, name), end='' if pct < 1 else '\n')
                wait(0.3)

            pct = 1
        else:
            while not is_finished() and pct < 1:
                elapsed = monotonic() - start
                rate = readable_bytes((self.copied / elapsed) if elapsed else 0)
                pct_chars = int(pct * 10)
                bar = '{}{}{}'.format('=' * pct_chars, next(spinner), ' ' * (9 - pct_chars))
                print(fmt.format(format_duration(int(elapsed)), rate, pct, bar, name), end='' if pct < 1 else '\n')
                wait(0.3)
                pct = self.copied / src_size

        if pct == 1:
            bar = '=' * 10
            print(fmt.format(format_duration(int(elapsed)), rate, pct, bar, name), end='' if pct < 1 else '\n')

    def copy_file(self):
        """
        Seems related to async writes, but hard to tell how to track:
        $ cat /proc/meminfo | egrep -v ' 0 kB'
        ...
        Dirty:             67288 kB
        Writeback:       1995224 kB
        ...
        NFS_Unstable:      24096 kB
        ...
        """
        sys.audit('ds_tools.fs.copy.copy_file', self.src_path, self.dst_path)
        with self.src_path.open('rb') as src, self.dst_path.open('wb') as dst:
            if self.fast:
                # if _USE_CP_SENDFILE and is_on_local_device(self.src_path):
                # if _USE_CP_SENDFILE and is_on_local_device(self.dst_path):
                if _USE_CP_SENDFILE:
                    try:
                        return self._fastcopy_sendfile(src, dst)
                    except _GiveupOnFastCopy:
                        pass  # fall back to the default copy method
                elif (_WINDOWS or self.reuse_buf) and self.src_size > 0:
                    # noinspection PyTypeChecker
                    return self._copyfileobj_readinto(src, dst, self.buf_size)

            self._copyfileobj(src, dst, self.buf_size)

    def _copyfileobj(self, src: BinaryIO, dst: BinaryIO, buf_size: int):
        log.debug(f'\nUsing _copyfileobj with {buf_size=:,d} b [loop of read buf_size -> write]')
        read, write = src.read, dst.write
        finished = self.finished.is_set
        while (buf := read(buf_size)) and not finished():
            self.copied += write(buf)

    def _copyfileobj_readinto(self, src, dst: BinaryIO, buf_size: int):
        """Based on :func:`shutil._copyfileobj_readinto`"""
        log.debug(f'\nUsing _copyfileobj_readinto with {buf_size=:,d} b [loop of readinto buf -> write]')
        src_readinto = src.readinto
        dst_write = dst.write
        buf = memoryview(bytearray(buf_size))
        finished = self.finished.is_set
        while (read := src_readinto(buf)) and not finished():
            if read < buf_size:
                # noinspection PyTypeChecker
                self.copied += dst_write(buf[:read])
            else:
                # noinspection PyTypeChecker
                self.copied += dst_write(buf)

    def _fastcopy_sendfile(self, src: BinaryIO, dst: BinaryIO):
        """Based on :func:`shutil._fastcopy_sendfile`"""
        try:
            in_fd = src.fileno()
            out_fd = dst.fileno()
        except Exception as e:
            raise _GiveupOnFastCopy(e)  # not a regular file

        buf_size = self.sendfile_buf_size
        log.debug(f'\nUsing _fastcopy_sendfile with {buf_size=:,d} b [loop of os.sendfile]')
        finished = self.finished.is_set
        try:
            while (sent := os.sendfile(out_fd, in_fd, self.copied, buf_size)) and not finished():
                self.copied += sent
        except OSError as e:
            e.filename = src.name  # provide more information in the error
            e.filename2 = dst.name
            if e.errno == errno.ENOTSOCK:
                global _USE_CP_SENDFILE
                # sendfile() on this platform (probably Linux < 2.6.33) does not support copies between regular
                # files (only sockets).
                _USE_CP_SENDFILE = False
                raise _GiveupOnFastCopy(e)
            elif e.errno == errno.ENOSPC:  # filesystem is full
                raise e from None
            elif self.copied == 0 and os.lseek(out_fd, 0, os.SEEK_CUR) == 0:
                raise _GiveupOnFastCopy(e)
            raise e

    def verify(self):
        log.info(f'Verifying copied file: {self.dst_path}')
        src_sha = sha512sum(self.src_path)
        log.debug(f'sha512 of {self.src_path} = {src_sha}')
        dst_sha = sha512sum(self.dst_path)
        log.debug(f'sha512 of {self.dst_path} = {dst_sha}')
        if src_sha != dst_sha:
            log.warning(f'Copy failed - sha512({self.src_path}) != sha512({self.dst_path})')
            log.warning(f'Deleting due to failed verification: {self.dst_path}')
            self.dst_path.unlink()
        else:
            log.info(f'Copy succeeded - sha512({self.src_path}) == sha512({self.dst_path})')


copy_file = FileCopy.copy


class _GiveupOnFastCopy(Exception):
    """Fallback to using raw read()/write() file copy when fast-copy functions fail to do so."""


def get_writeback_size():
    with open('/proc/meminfo', 'rb') as f:
        for line in f:
            if line.startswith(b'Writeback:'):
                return int(line.split()[1]) * 1024
    return 0
