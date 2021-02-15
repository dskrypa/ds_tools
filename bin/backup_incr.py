#!/usr/bin/env python

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, PROJECT_ROOT.joinpath('bin').as_posix())
import _venv  # This will activate the venv, if it exists and is not already active

import logging
import shutil

sys.path.append(PROJECT_ROOT.as_posix())
from ds_tools.__version__ import __author_email__, __version__
from ds_tools.argparsing import ArgParser
from ds_tools.core import wrap_main
from ds_tools.fs.paths import iter_sorted_files
from ds_tools.logging import init_logging

log = logging.getLogger(__name__)
IGNORE_FILES = {'Thumbs.db'}
IGNORE_DIRS = {'__pycache__', '.git', '.idea'}


def parser():
    parser = ArgParser(description='Incremental Backup Tool')
    parser.add_argument('source', metavar='PATH', help='The file to backup')
    parser.add_argument('last_dir', metavar='PATH', help='The directory in which the last backup was stored')
    parser.add_argument('dest_dir', metavar='PATH', help='The directory in which backups should be stored')
    parser.add_argument('--ignore_files', nargs='+', help='Add additional file names to be ignored')
    parser.add_argument('--ignore_dirs', nargs='+', help='Add additional directory names to be ignored')
    parser.add_argument('--follow_links', '-L', action='store_true', help='Follow directory symlinks')
    parser.include_common_args('verbosity', 'dry_run')
    return parser


@wrap_main
def main():
    args = parser().parse_args()
    init_logging(args.verbose)

    if args.ignore_files:
        IGNORE_FILES.update(args.ignore_files)
    if args.ignore_dirs:
        IGNORE_DIRS.update(args.ignore_dirs)

    dry_run = args.dry_run
    src_root = Path(args.source).expanduser().resolve()
    prv_root = Path(args.last_dir).expanduser().resolve()
    new_root = Path(args.dest_dir).expanduser().resolve()
    prefix = '[DRY RUN] Would backup' if dry_run else 'Backing up'

    for src_path in iter_sorted_files(src_root, IGNORE_DIRS, IGNORE_FILES, args.follow_links):
        rel_path = src_path.relative_to(src_root)
        prv_path = prv_root.joinpath(rel_path)
        if prv_path.exists():
            src_stat = src_path.stat()
            prv_stat = prv_path.stat()
            if src_stat.st_size == prv_stat.st_size and src_stat.st_mtime == prv_stat.st_mtime:
                log.debug(f'Skipping previously backed up file: {rel_path}')
            else:
                backup_file(src_path, new_root, rel_path, prefix, dry_run, 'modified')
        else:
            backup_file(src_path, new_root, rel_path, prefix, dry_run, 'new')


def backup_file(src_path: Path, new_root: Path, rel_path: Path, prefix: str, dry_run: bool, adj: str):
    new_path = new_root.joinpath(rel_path)
    if new_path.exists():
        log.log(19, f'Skipping {rel_path} because it already exists in {new_root}')
    else:
        log.info(f'{prefix} {adj} {rel_path}')
        if not dry_run:
            dest_dir = new_path.parent
            if not dest_dir.exists():
                dest_dir.mkdir(parents=True)
            shutil.copy(src_path, new_path)


if __name__ == '__main__':
    main()
