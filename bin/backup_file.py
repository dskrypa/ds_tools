#!/usr/bin/env python

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, PROJECT_ROOT.joinpath('bin').as_posix())
import _venv  # This will activate the venv, if it exists and is not already active

import logging
import shutil
from datetime import datetime

sys.path.append(PROJECT_ROOT.as_posix())
from ds_tools.__version__ import __author_email__, __version__
from ds_tools.argparsing import ArgParser
from ds_tools.core.main import wrap_main
from ds_tools.fs.hash import sha512sum
from ds_tools.logging import init_logging

log = logging.getLogger(__name__)


def parser():
    parser = ArgParser(description='File Backup Tool')
    parser.add_argument('source', metavar='PATH', help='The file to backup')
    parser.add_argument('dest_dir', metavar='PATH', help='The directory in which backups should be stored')

    opt_group = parser.add_argument_group('Behavior Options')
    opt_group.add_argument('--always', '-a', action='store_true', help='Always make a backup, even if the source file has not changed')

    parser.include_common_args('verbosity', 'dry_run')
    return parser


@wrap_main
def main():
    args = parser().parse_args()
    init_logging(args.verbose)

    source = Path(args.source).expanduser()
    if not source.is_file():
        raise ValueError(f'Invalid {source=} file - does not exist or is not a file')
    dest_dir = Path(args.dest_dir).expanduser()
    if dest_dir.exists() and not dest_dir.is_dir():
        raise ValueError(f'Invalid {dest_dir=} directory - is not a directory')
    elif not dest_dir.exists():
        dest_dir.mkdir(parents=True)

    latest = get_latest_backup(dest_dir)
    if latest is None or args.always or sha512sum(source) != sha512sum(latest):
        backup_file(source, dest_dir, args.dry_run)
    else:
        log.info(f'Skipping backup of {source} - it has not changed compared to {latest=!s}')


def backup_file(source: Path, dest_dir: Path, dry_run: bool):
    dest = dest_path(source, dest_dir)
    if dry_run:
        log.info(f'[DRY RUN] Would copy {source} -> {dest}')
    else:
        log.info(f'Copying {source} -> {dest}')
        shutil.copy(source, dest)


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
