"""
Utilities for copying files with a progress indicator

:author: Doug Skrypa
"""

import logging
import time
from concurrent import futures
from itertools import cycle
from pathlib import Path
from threading import Event

from tz_aware_dt import format_duration
from ..output import readable_bytes
from .hash import sha512sum

__all__ = ['copy_file']
log = logging.getLogger(__name__)


def copy_file(src_path, dst_path, verify=False, block_size=10485760):
    """
    :param Path src_path: Source path
    :param Path dst_path: Destination path
    :param bool verify: Verify integrity of copied file
    :param int block_size: Number of bytes to read at a time (default: 10MB)
    """
    src_path = Path(src_path).expanduser() if not isinstance(src_path, Path) else src_path
    dst_path = Path(dst_path).expanduser() if not isinstance(dst_path, Path) else dst_path
    if dst_path.exists():
        raise FileExistsError('File already exists: {}'.format(dst_path))
    if not dst_path.parent.exists():
        dst_path.parent.mkdir(parents=True)

    src_size = src_path.stat().st_size
    fmt = '\r{{:8}} {{:>9}}/s {{:6.2%}} [{{:10}}] [{}] {}'.format(readable_bytes(src_size), src_path.name)
    spinner = cycle('|/-\\')
    copied = 0
    elapsed = 0
    finished = Event()

    def update_progress(_copied, _elapsed):
        nonlocal copied, elapsed
        copied = _copied
        elapsed = _elapsed

    def show_progress():
        # Run this in a separate thread so that it doesn't slow down the copy thread
        pct = copied / src_size
        rate = readable_bytes((copied / elapsed) if elapsed else 0)
        while not finished.is_set() and pct < 1:
            rate = readable_bytes((copied / elapsed) if elapsed else 0)
            pct_chars = int(pct * 10)
            bar = '{}{}{}'.format('=' * pct_chars, next(spinner), ' ' * (9 - pct_chars))
            print(fmt.format(format_duration(int(elapsed)), rate, pct, bar), end='' if pct < 1 else '\n')
            finished.wait(0.3)
            pct = copied / src_size

        if pct == 1:
            bar = '=' * 10
            print(fmt.format(format_duration(int(elapsed)), rate, pct, bar), end='' if pct < 1 else '\n')

    with futures.ThreadPoolExecutor(max_workers=2) as executor:
        _futures = [
            executor.submit(_copy_file, src_path, dst_path, update_progress, verify, block_size),
            executor.submit(show_progress)
        ]
        for future in futures.as_completed(_futures):
            try:
                future.result()
            except BaseException:
                finished.set()
                print()
                if dst_path.exists():
                    log.warning('Deleting incomplete {}'.format(dst_path))
                    dst_path.unlink()
                raise

    if verify:
        log.info('Verifying copied file: {}'.format(dst_path))
        src_sha = sha512sum(src_path)
        log.debug('sha512 of {} = {}'.format(src_path, src_sha))
        dst_sha = sha512sum(dst_path)
        log.debug('sha512 of {} = {}'.format(dst_path, dst_sha))
        if src_sha != dst_sha:
            log.warning('Copy failed - sha512({}) != sha512({})'.format(src_path, dst_path))
            log.warning('Deleting due to failed verification: {}'.format(dst_path))
            dst_path.unlink()
        else:
            log.info('Copy succeeded - sha512({}) == sha512({})'.format(src_path, dst_path))


def _copy_file(src_path, dst_path, cb, verify=False, block_size=10485760):
    """
    :param Path src_path: Source path
    :param Path dst_path: Destination path
    :param function cb: A callback function that takes arguments (copied, elapsed)
    :param bool verify: Verify integrity of copied file
    :param int block_size: Number of bytes to read at a time (default: 10MB)
    """
    copied = 0
    start = time.monotonic()
    with src_path.open('rb') as src, dst_path.open('wb') as dst:
        # TODO: Use a bytearray/memoryview?
        while buf := src.read(block_size):
            copied += dst.write(buf)
            elapsed = time.monotonic() - start
            if elapsed >= 0.3:
                cb(copied, elapsed)

        elapsed = time.monotonic() - start
        cb(copied, elapsed)
