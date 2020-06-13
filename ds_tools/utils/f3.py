"""
Utilities for generating disk test data, based on F3: https://github.com/AltraMayor/f3

:author: Doug Skrypa
"""

import logging
import time
from enum import Enum
from errno import ENOSPC
from hashlib import sha512
from pathlib import Path
from shutil import disk_usage
from typing import Union

import cffi

from tz_aware_dt import format_duration
from ..output import readable_bytes, colored

__all__ = ['DEFAULT_CHUNK_SIZE', 'GB_BYTES', 'F3Data', 'F3Mode']
log = logging.getLogger(__name__)

GB_BYTES = 1073741824
DEFAULT_CHUNK_SIZE = 1 << 21    # 2MB

ffi = cffi.FFI()
ffi.cdef('static uint64_t fill_buffer(void *buf, size_t size, uint64_t offset);')
fill_buffer = ffi.verify("""
#define SECTOR_SIZE 512
#define GIGABYTES 1073741824

static inline uint64_t random_number(uint64_t prv_number)
{
	return prv_number * 4294967311ULL + 17;
}

static uint64_t fill_buffer(void *buf, size_t size, uint64_t offset)
{
	const int num_int64 = SECTOR_SIZE >> 3;
	uint8_t *p, *ptr_end;

	assert(size > 0);
	assert(size % SECTOR_SIZE == 0);

	p = buf;
	ptr_end = p + size;
	while (p < ptr_end) {
		uint64_t *sector = (uint64_t *)p;
		int i;
		sector[0] = offset;
		for (i = 1; i < num_int64; i++)
			sector[i] = random_number(sector[i - 1]);
		p += SECTOR_SIZE;
		offset += SECTOR_SIZE;
	}

	return offset;
}
""").fill_buffer


class F3Mode(Enum):
    ITER = 'iter'
    FULL = 'full'


class F3Data:
    def __init__(self, mode, size: int = GB_BYTES, chunk_size: int = DEFAULT_CHUNK_SIZE):
        self.mode = F3Mode(mode)
        if chunk_size > size:
            chunk_size = size
        self.size = size
        self.chunk_size = chunk_size
        self.buf = bytearray(size if self.mode == F3Mode.FULL else chunk_size)
        self.view = memoryview(self.buf)

    def iter_data(self, num: int):
        size, chunk_size = self.size, self.chunk_size
        view, buf = self.view, self.buf
        offset = (num - 1) * size
        from_buffer = ffi.from_buffer
        for start in range(0, size, chunk_size):
            offset = fill_buffer(from_buffer(view), chunk_size, offset)
            yield buf

    def data(self, num: int):
        size, chunk_size, view = self.size, self.chunk_size, self.view
        offset = (num - 1) * size
        from_buffer = ffi.from_buffer
        for start in range(0, size, chunk_size):
            end = start + chunk_size
            chunk = view[start:end]
            offset = fill_buffer(from_buffer(chunk), chunk_size, offset)
        return self.buf

    def _write_file(self, path: Path, num: int):
        print(f'Writing file {path.name} ... ', end='', flush=True)
        mode = self.mode
        if mode == F3Mode.FULL:
            data = self.data(num)
            with path.open('wb') as f:
                f.write(data)
        elif mode == F3Mode.ITER:
            with path.open('wb') as f:
                for chunk in self.iter_data(num):
                    f.write(chunk)

    def write_files(self, path: Union[str, Path], start, end=None, rewrite=False):
        path = Path(path).resolve()
        if not path.exists():
            path.mkdir(parents=True)

        free = disk_usage(path)[2]
        end = end if end is not None else (free // GB_BYTES)
        if end < start:
            raise ValueError('end must be greater than start')
        size = self.size

        if not rewrite:
            for num in range(start, end + 1):
                file_path = path.joinpath(f'{num}.h2w')
                if file_path.exists():
                    if file_path.stat().st_size != size:
                        start = num
                        log.info(f'Starting from incomplete {num=} (use --rewrite to overwrite all existing files)')
                        break
                else:
                    if num != start:
                        start = num
                        log.info(f'Starting from {num=} (use --rewrite to overwrite all existing files)')
                    break
            else:
                log.info(f'All expected files already exist (use --rewrite to overwrite all existing files)')
                return

        total = end - start + 1
        log.info(f'Writing {total:,d} files to {path} [free space: {readable_bytes(free)}]\n')
        start_time = time.monotonic()
        for i, num in enumerate(range(start, end + 1), 1):
            file_path = path.joinpath(f'{num}.h2w')
            try:
                self._write_file(file_path, num)
            except OSError as e:
                if e.errno == ENOSPC:
                    log.info(f'OK (No space left in {path})')
                    return True
                else:
                    print('ERROR')
                    log.error(f'Unexpected error:', exc_info=True)
                    return False
            except Exception:
                print('ERROR')
                log.error(f'Unexpected error:', exc_info=True)
                return False
            else:
                elapsed = time.monotonic() - start_time
                bps = (i * size / elapsed) if elapsed else 0
                remaining = ((total - i) * size / bps) if bps else 0
                log.info(
                    f'OK [Elapsed: {format_duration(elapsed)}] [{readable_bytes(bps)}/s] '
                    f'[Est. Remaining: {format_duration(remaining)}]'
                )
        else:
            return True

    def hash_for(self, num: int) -> str:
        _hash = sha512()
        _update = _hash.update
        for chunk in self.iter_data(num):
            _update(chunk)
        return _hash.hexdigest()

    def verify_file(self, path: Path, chunk_size: int = DEFAULT_CHUNK_SIZE):
        if path.suffix != '.h2w':
            log.debug(f'Skipping file={path}')
            return None
        try:
            num = int(path.stem)
        except Exception:
            log.debug(f'Skipping file={path}')
            return None

        expected = self.hash_for(num)

        with path.open('rb') as f:
            _hash = sha512()
            _update = _hash.update
            while chunk := f.read(chunk_size):
                _update(chunk)
            actual = _hash.hexdigest()

        if expected == actual:
            log.info(f'{path.name} ... {colored("OK", "green")}')
            return True
        else:
            log.warning(f'{path.name} ... {colored("BAD", "red")} {expected=!r} {actual=!r}')
            return False

    def verify_files(self, path: Union[str, Path], chunk_size: int = DEFAULT_CHUNK_SIZE):
        path = Path(path).resolve()
        if not path.exists():
            raise ValueError(f'Path does not exist: {path}')
        elif not path.is_dir():
            raise ValueError(f'Invalid {path=} - expected a directory')

        ok, bad = 0, 0
        for file in path.iterdir():
            if file.is_file():
                result = self.verify_file(file, chunk_size)
                if result is not None:
                    if result:
                        ok += 1
                    else:
                        bad += 1

        total = ok + bad
        if ok:
            log.info(f'\n{ok:,d} / {total:,d} files are {colored("OK", "green")}')
        if bad:
            log.info(f'{bad:,d} / {total:,d} files are {colored("BAD", "red")}')
        return bad == 0
