#!/usr/bin/env python
"""
Sort JPGs by their EXIF dates

:author: Doug Skrypa
"""

import logging
import sys
from datetime import datetime
from pathlib import Path

from exifread import process_file

sys.path.append(Path(__file__).resolve().parents[1].as_posix())
from ds_tools.argparsing import ArgParser
from ds_tools.logging import init_logging

log = logging.getLogger('ds_tools.{}'.format(__name__))


def parser():
    parser = ArgParser(description='EXIF Sorter')
    parser.add_argument('source', help='Path of the directory to sort from')
    parser.add_argument('target', help='Path of the directory to sort to')
    parser.include_common_args('verbosity', 'dry_run')
    return parser


def main():
    args = parser().parse_args()
    init_logging(args.verbose, log_path=None)

    dry_run = args.dry_run
    src_dir = Path(args.source)
    dest_dir = Path(args.target)
    for file in src_dir.iterdir():
        if file.suffix.lower() in ('.jpg', '.jpeg'):
            try:
                with file.open('rb') as f:
                    jpg = process_file(f)
                    date_taken = datetime.strptime(jpg['EXIF DateTimeOriginal'].values, '%Y:%m:%d %H:%M:%S')
            except Exception as e:
                log.error('Error processing {}: {}'.format(file, e))
            else:
                day_str = date_taken.strftime('%Y-%m-%d')
                day_dir = dest_dir.joinpath(day_str)
                if not day_dir.exists():
                    if dry_run:
                        log.info('[DRY RUN] Would create {}'.format(day_dir))
                    else:
                        log.log(19, 'Creating {}'.format(day_dir))
                        day_dir.mkdir(parents=True)
                dest_file = day_dir.joinpath(file.name)
                if dest_file.exists():
                    log.error('Already exists: {}'.format(dest_file))
                else:
                    if dry_run:
                        log.info('[DRY RUN] Would move {} -> {}'.format(file, dest_file))
                    else:
                        log.log(19, 'Moving {} -> {}'.format(file, dest_file))
                        file.rename(dest_file)
        else:
            log.log(19, 'Skipping {}'.format(file))


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print()

