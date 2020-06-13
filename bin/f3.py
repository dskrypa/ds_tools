#!/usr/bin/env python
"""
Utility based on f3write: https://github.com/AltraMayor/f3

:author: Doug Skrypa
"""

import logging
import sys
from pathlib import Path

sys.path.append(Path(__file__).resolve().parents[1].as_posix())
from ds_tools.__version__ import __author_email__, __version__
from ds_tools.argparsing import ArgParser
from ds_tools.core import wrap_main
from ds_tools.input import parse_bytes
from ds_tools.logging import init_logging
from ds_tools.utils.f3 import GB_BYTES, DEFAULT_CHUNK_SIZE, F3Mode, F3Data

log = logging.getLogger(__name__)


def parser():
    parser = ArgParser(description='Alternate F3 Write/Read Test')

    write_parser = parser.add_subparser('action', 'write', 'Equivalent of f3write, with more options')
    write_parser.add_argument('path', help='The directory in which files should be written')
    write_parser.add_argument('--start', '-s', type=int, default=1, help='The number for the first file to be written')
    write_parser.add_argument('--end', '-e', type=int, help='The number for the last file to be written (default: fill disk)')
    write_parser.add_argument('--size', '-S', metavar='BYTES', type=parse_bytes, default=GB_BYTES, help='File size to use (this is for testing purposes only)')
    write_parser.add_argument('--chunk_size', '-c', metavar='BYTES', type=parse_bytes, default=DEFAULT_CHUNK_SIZE, help='Chunk size to use (default: %(default)s)')
    write_parser.add_argument('--mode', '-m', choices=[e.value for e in F3Mode], default='iter', help='Buffer population mode (default: %(default)s)')

    read_parser = parser.add_subparser('action', 'read', 'Simplified version of f3read')
    read_parser.add_argument('path', help='The directory from which files should be read')
    read_parser.add_argument('--chunk_size', '-c', metavar='BYTES', type=parse_bytes, default=DEFAULT_CHUNK_SIZE, help='Chunk size to use (default: %(default)s)')
    read_parser.add_constant('mode', 'iter')
    read_parser.add_constant('size', GB_BYTES)

    parser.include_common_args('verbosity')
    return parser


@wrap_main
def main():
    args = parser().parse_args()
    init_logging(args.verbose, log_path=None)

    f3data = F3Data(args.mode, args.size, args.chunk_size)
    action = args.action
    if action == 'write':
        if not f3data.write_files(args.path, args.start, args.end):
            sys.exit(1)
    elif action == 'read':
        if not f3data.verify_files(args.path, args.chunk_size):
            sys.exit(1)
    else:
        raise ValueError(f'Unexpected {action=!r}')


if __name__ == '__main__':
    main()
