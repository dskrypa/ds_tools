#!/usr/bin/env python

import sys
from pathlib import Path

sys.path.insert(0, Path(__file__).resolve().parents[1].joinpath('bin').as_posix())
import _venv  # This will activate the venv, if it exists and is not already active

import logging
from datetime import datetime, timedelta

from ds_tools.argparsing import ArgParser
from ds_tools.logging import init_logging

log = logging.getLogger(__name__)


def parser():
    parser = ArgParser(description='Subtitle Offset Adjuster')
    parser.add_argument('subtitle_file', metavar='PATH', help='Path to the subtitle file to modify')
    parser.add_argument('--offset', '-o', type=float, required=True, help='Offset in seconds')
    parser.include_common_args('verbosity')
    return parser


def main():
    args = parser().parse_args()
    init_logging(args.verbose, log_path=None)

    original = Path(args.subtitle_file)
    backup = Path(args.subtitle_file + '.bkp')

    path = backup if backup.exists() else original
    revised = update_timestamps(path, args.offset)

    if not backup.exists():
        log.info(f'Saving backup: {backup.as_posix()}')
        original.rename(backup)

    with original.open('w', encoding='utf-8') as f:
        f.write('\n'.join(revised))

    log.info(f'Updated {original.as_posix()}')


def update_timestamps(path, offset: float):
    fmt = '%H:%M:%S,%f'

    with open(path, 'r', encoding='utf-8') as f:
        lines = f.read().splitlines()

    revised = []
    for line in map(str.strip, lines):
        try:
            a, b = line.split(' --> ')
        except Exception:
            revised.append(line)
        else:
            # print(f'Processing a={a!r} b={b!r}')
            a = datetime.strptime(a, fmt) + timedelta(seconds=offset)
            b = datetime.strptime(b, fmt) + timedelta(seconds=offset)
            revised.append(f'{a.strftime(fmt)[:-3]} --> {b.strftime(fmt)[:-3]}')

    return revised


if __name__ == '__main__':
    main()
