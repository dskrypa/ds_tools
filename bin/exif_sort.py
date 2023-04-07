#!/usr/bin/env python

import logging
from datetime import datetime

from cli_command_parser import Command, Positional, Flag, Counter, main, inputs

log = logging.getLogger(__name__)


class Command0(Command, description='Sorts JPGs by their EXIF dates'):
    src_dir = Positional(type=inputs.Path(type='dir', exists=True), help='Path of the directory to sort from')
    dst_dir = Positional(type=inputs.Path(type='dir'), help='Path of the directory to sort to')
    verbose = Counter('-v', help='Increase logging verbosity (can specify multiple times)')
    dry_run = Flag('-D', help='Print the actions that would be taken instead of taking them')

    def _init_command_(self):
        from ds_tools.logging import init_logging

        init_logging(self.verbose, log_path=None)

    def main(self):
        from exifread import process_file
        from ds_tools.output.prefix import LoggingPrefix

        lp = LoggingPrefix(self.dry_run)
        for file in self.src_dir.iterdir():
            if file.suffix.lower() in ('.jpg', '.jpeg'):
                try:
                    with file.open('rb') as f:
                        jpg = process_file(f)
                        date_taken = datetime.strptime(jpg['EXIF DateTimeOriginal'].values, '%Y:%m:%d %H:%M:%S')
                except Exception as e:
                    log.error(f'Error processing {file}: {e}')
                else:
                    day_str = date_taken.strftime('%Y-%m-%d')
                    day_dir = self.dst_dir.joinpath(day_str)
                    if not day_dir.exists():
                        log.info(f'{lp.create} {day_dir}')
                        if not self.dry_run:
                            day_dir.mkdir(parents=True)

                    dest_file = day_dir.joinpath(file.name)
                    if dest_file.exists():
                        log.error(f'Already exists: {dest_file}')
                    else:
                        log.info(f'{lp.move} {file} -> {dest_file}')
                        if not self.dry_run:
                            file.rename(dest_file)
            else:
                log.log(19, f'Skipping {file}')


if __name__ == '__main__':
    main()
