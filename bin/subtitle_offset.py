#!/usr/bin/env python

from argparse import ArgumentParser
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable


def parser():
    parser = ArgumentParser(description='Subtitle Offset Adjuster')
    parser.add_argument('subtitle_file', metavar='PATH', help='Path to the subtitle file to modify (timestamps will be read from .bkp file with the same name if it already exists)')
    parser.add_argument('--offset', '-o', type=float, required=True, help='Offset in seconds')
    return parser


def main():
    args = parser().parse_args()

    orig_path = Path(args.subtitle_file)
    backup_path = Path(args.subtitle_file + '.bkp')

    read_path = backup_path if backup_path.exists() else orig_path
    with read_path.open('r', encoding='utf-8') as f:
        original = f.read().splitlines()

    revised = update_timestamps(original, timedelta(seconds=args.offset))

    if not backup_path.exists():
        print(f'Saving backup: {backup_path.as_posix()}')
        orig_path.rename(backup_path)

    with orig_path.open('w', encoding='utf-8') as f:
        f.write('\n'.join(revised))

    print(f'Updated {orig_path.as_posix()}')


def update_timestamps(original: Iterable[str], offset: timedelta):
    fmt = '%H:%M:%S,%f'

    revised = []
    for line in map(str.strip, original):
        try:
            a, b = line.split(' --> ')
        except ValueError:
            revised.append(line)
        else:
            # print(f'Processing a={a!r} b={b!r}')
            a = datetime.strptime(a, fmt) + offset
            b = datetime.strptime(b, fmt) + offset
            revised.append(f'{a.strftime(fmt)[:-3]} --> {b.strftime(fmt)[:-3]}')

    return revised


if __name__ == '__main__':
    main()
