#!/usr/bin/env python

import logging
import shutil
from datetime import datetime
from pathlib import Path

from cli_command_parser import Command, ParamGroup, Positional, Flag, Counter, main, inputs

from ds_tools.__version__ import __author_email__, __version__  # noqa
from ds_tools.fs.hash import sha512sum

log = logging.getLogger(__name__)


class BackupUtil(Command, description='File Backup Tool'):
    src_file: Path = Positional(type=inputs.Path(type='file', exists=True), help='The file to backup')
    dst_dir = Positional(type=inputs.Path(type='dir'), help='The directory in which backups should be stored')
    verbose = Counter('-v', help='Increase logging verbosity (can specify multiple times)')
    dry_run = Flag('-D', help='Print the actions that would be taken instead of taking them')

    with ParamGroup(description='Behavior Options'):
        always = Flag('-a', help='Always make a backup, even if the source file has not changed')

    def _init_command_(self):
        from ds_tools.logging import init_logging

        init_logging(self.verbose, log_path=None)

    def main(self):
        from ds_tools.output.prefix import LoggingPrefix

        lp = LoggingPrefix(self.dry_run)
        if not self.dry_run and not self.dst_dir.exists():
            self.dst_dir.mkdir(parents=True)

        latest = get_latest_backup(self.dst_dir)
        if latest is None or self.always or sha512sum(self.src_file) != sha512sum(latest):
            dst_path = dest_path(self.src_file, self.dst_dir)
            log.info(f'{lp.copy} {self.src_file.as_posix()} -> {dst_path.as_posix()}')
            if not self.dry_run:
                shutil.copy(self.src_file, dst_path)
        else:
            log.info(f'Skipping backup of {self.src_file} - it has not changed compared to {latest=!s}')


def dest_path(source: Path, dest_dir: Path):
    timestamp = datetime.now().strftime('%Y-%m-%d')
    path = dest_dir.joinpath(source.with_name(f'{source.stem}_{timestamp}{source.suffix}').name)
    i = 1
    while path.exists():
        path = dest_dir.joinpath(source.with_name(f'{source.stem}_{timestamp}_{i}{source.suffix}').name)
        i += 1
    return path


def get_latest_backup(backup_dir: Path):
    latest = None
    latest_time = None
    for path in backup_dir.iterdir():
        if path.is_file():
            modtime = path.stat().st_mtime
            if latest_time is None or modtime > latest_time:
                latest_time = modtime
                latest = path

    return latest


if __name__ == '__main__':
    main()
