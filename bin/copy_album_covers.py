#!/usr/bin/env python

from pathlib import Path
from shutil import copy2

from cli_command_parser import Command, Option, Flag, Counter, main
from cli_command_parser.inputs import Path as IPath

from ds_tools.__version__ import __author_email__, __version__  # noqa


class CopyImages(Command, description='Copy Images', option_name_mode='*-'):
    in_paths = Option(
        '-i', required=True, nargs='+', help='One or more image files or directories containing image files to copy'
    )
    out_dir: Path = Option('-o', required=True, type=IPath(type='dir'), help='Output directory')
    verbose = Counter('-v', help='Increase logging verbosity (can specify multiple times)')
    dry_run = Flag('-D', help='Print the actions that would be taken instead of taking them')

    def _init_command_(self):
        from ds_tools.logging import init_logging

        init_logging(self.verbose, log_path=None)

    def main(self):
        from ds_tools.fs.paths import iter_files

        if not self.dry_run:
            self.out_dir.mkdir(parents=True, exist_ok=True)

        prefix = '[DRY RUN] Would copy' if self.dry_run else 'Copying'
        ext_allow_list = {'.jpg', '.jpeg', '.png'}
        for path in iter_files(self.in_paths):
            if path.suffix.lower() not in ext_allow_list:
                continue

            dst_name = f'{path.parents[2].name} - {path.parent.name} - {path.name}'
            dst_path = self.out_dir.joinpath(dst_name)
            print(f'{prefix} {path.as_posix()} -> {dst_path.as_posix()}')
            if not self.dry_run:
                copy2(path, dst_path)


if __name__ == '__main__':
    main()
