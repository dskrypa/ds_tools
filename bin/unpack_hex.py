#!/usr/bin/env python

import sys
from pathlib import Path

sys.path.insert(0, Path(__file__).resolve().parents[1].joinpath('bin').as_posix())
import _venv  # This will activate the venv, if it exists and is not already active

import logging
from io import BytesIO

from ds_tools.argparsing import ArgParser
from ds_tools.logging import init_logging
from ds_tools.misc.binary import view_unpacked

log = logging.getLogger(__name__)


def parser():
    parser = ArgParser(description='View hex data as unpacked structs')
    parser.add_argument('data', help='A hex string')
    parser.add_argument('--offset', '-o', type=int, default=0, help='Offset from the beginning of the data in bytes to start struct matching')
    parser.add_argument('--endian', '-e', choices=('big', 'little', 'native'), help='Interpret values with the given endianness')
    parser.include_common_args('verbosity')
    return parser


def main():
    args = parser().parse_args()
    init_logging(args.verbose, log_path=None)

    data = args.data
    if not len(data) % 2 == 0:
        raise ValueError('Invalid data - length must be divisible by 2')

    bio = BytesIO()
    for i in range(0, len(data), 2):
        bio.write(bytes.fromhex(data[i: i + 2]))
        # bio.write(int(data[i: i + 2], 16).to_bytes())

    for key, val in view_unpacked(bio.getvalue(), offset=args.offset, endian=args.endian).items():
        print(f'{key}: {val}')


if __name__ == '__main__':
    main()
