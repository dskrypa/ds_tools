"""
Utilities for copying files with a progress indicator

:author: Doug Skrypa
"""

import logging
from concurrent import futures
from itertools import cycle
from pathlib import Path
from threading import Event
from time import monotonic
from typing import Union

from tz_aware_dt.utils import format_duration
from ..output.formatting import readable_bytes
from .hash import sha512sum

__all__ = ['copy_file']
log = logging.getLogger(__name__)


class FileCopy:
    def __init__(self, src_path: Union[str, Path], dst_path: Union[str, Path], block_size: int = 10485760):
        self.src_path = Path(src_path).expanduser() if not isinstance(src_path, Path) else src_path
        self.dst_path = Path(dst_path).expanduser() if not isinstance(dst_path, Path) else dst_path
        if self.dst_path.exists():
            raise FileExistsError(f'File already exists: {dst_path}')
        if not self.dst_path.parent.exists():
            self.dst_path.parent.mkdir(parents=True)
        self.copied = 0
        self.finished = Event()
        self.block_size = block_size

    @classmethod
    def copy(
        cls, src_path: Union[str, Path], dst_path: Union[str, Path], verify: bool = False, block_size: int = 10485760
    ):
        """
        :param Path src_path: Source path
        :param Path dst_path: Destination path
        :param bool verify: Verify integrity of copied file
        :param int block_size: Number of bytes to read at a time (default: 10MB)
        """
        cls(src_path, dst_path, block_size).run(verify)

    def run(self, verify: bool = False):
        with futures.ThreadPoolExecutor(max_workers=2) as executor:
            _futures = [executor.submit(self.copy_file), executor.submit(self.show_progress)]
            for future in futures.as_completed(_futures):
                try:
                    future.result()
                except BaseException:
                    self.finished.set()
                    print()
                    if self.dst_path.exists():
                        log.warning(f'Deleting incomplete {self.dst_path}')
                        self.dst_path.unlink()
                    raise

        if verify:
            self.verify()

    def show_progress(self):
        # Run this in a separate thread so that it doesn't slow down the copy thread
        src_size = self.src_path.stat().st_size
        pct, elapsed, rate = 0, 0, readable_bytes(0)
        spinner = cycle('|/-\\')
        fmt = '\r{{:8}} {{:>9}}/s {{:6.2%}} [{{:10}}] [{}] {}'.format(readable_bytes(src_size), self.src_path.name)
        is_finished, wait = self.finished.is_set, self.finished.wait
        start = monotonic()
        while not is_finished() and pct < 1:
            elapsed = monotonic() - start
            rate = readable_bytes((self.copied / elapsed) if elapsed else 0)
            pct_chars = int(pct * 10)
            bar = '{}{}{}'.format('=' * pct_chars, next(spinner), ' ' * (9 - pct_chars))
            print(fmt.format(format_duration(int(elapsed)), rate, pct, bar), end='' if pct < 1 else '\n')
            wait(0.3)
            pct = self.copied / src_size

        if pct == 1:
            bar = '=' * 10
            print(fmt.format(format_duration(int(elapsed)), rate, pct, bar), end='' if pct < 1 else '\n')

    def copy_file(self):
        block_size = self.block_size
        with self.src_path.open('rb') as src, self.dst_path.open('wb') as dst:
            read, write = src.read, dst.write
            while buf := read(block_size):
                self.copied += write(buf)

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
