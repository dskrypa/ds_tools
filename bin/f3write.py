#!/usr/bin/env python

import logging
import sys
import time
from errno import ENOSPC
from pathlib import Path
from shutil import disk_usage

import cffi

from tz_aware_dt import format_duration

sys.path.append(Path(__file__).resolve().parents[1].as_posix())
from ds_tools.__version__ import __author_email__, __version__
from ds_tools.argparsing import ArgParser
from ds_tools.core import wrap_main
from ds_tools.input import parse_bytes
from ds_tools.logging import init_logging
from ds_tools.output import readable_bytes

log = logging.getLogger(__name__)
GB_BYTES = 1073741824
MAX_WRITE_SIZE = 1 << 21    # 2MB

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


def parser():
    parser = ArgParser(description='F3 Write Replacement Script')
    parser.add_argument('path', help='The directory in which files should be written')
    parser.add_argument('--start', '-s', type=int, default=1, help='The number for the first file to be written')
    parser.add_argument('--end', '-e', type=int, help='The number for the last file to be written (default: fill disk)')
    parser.add_argument('--size', '-S', type=parse_bytes, default=GB_BYTES, help='File size to use (this is for testing purposes only)')
    parser.include_common_args('verbosity')
    return parser


@wrap_main
def main():
    args = parser().parse_args()
    init_logging(args.verbose, log_path=None)

    dir_path = Path(args.path).resolve()
    if not dir_path.exists():
        dir_path.mkdir(parents=True)

    end = args.end or (disk_usage(dir_path)[2] // GB_BYTES)
    if not write_files(dir_path, args.start, end, args.size):
        sys.exit(1)


def get_data(num: int, chunk_size: int = MAX_WRITE_SIZE, size: int = GB_BYTES):
    offset = num * size
    buffer = bytearray(size)
    view = memoryview(buffer)
    if chunk_size > size:
        chunk_size = size

    from_buffer = ffi.from_buffer
    for start in range(0, size, chunk_size):
        end = start + chunk_size
        chunk = view[start:end]
        offset = fill_buffer(from_buffer(chunk), chunk_size, offset)
    return buffer


def write_file(dir_path: Path, num: int, size: int):
    file_path = dir_path.joinpath(f'{num}.h2w')
    print(f'Writing file {file_path.name} ... ', end='', flush=True)
    buf = get_data(num - 1, size=size)
    with file_path.open('wb') as f:
        f.write(buf)


def write_files(dir_path, start, end, size):
    if end < start:
        raise ValueError('--end must be greater than --start')
    total = end - start + 1
    free = disk_usage(dir_path)[2]
    log.info(f'Writing {total:,d} files to {dir_path} [free space: {readable_bytes(free)}]\n')
    start_time = time.monotonic()
    for i, num in enumerate(range(start, end + 1), 1):
        try:
            write_file(dir_path, num, size)
        except OSError as e:
            if e.errno == ENOSPC:
                log.info(f'OK (No space left in {dir_path})')
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
            elapsed = int(time.monotonic() - start_time)
            bps = i * size / elapsed
            remaining = (total - i) * size / bps
            log.info(
                f'OK [Elapsed: {format_duration(elapsed)}] [{readable_bytes(bps)}/s] '
                f'[Est. Remaining: {format_duration(remaining)}]'
            )
    else:
        return True


if __name__ == '__main__':
    main()
