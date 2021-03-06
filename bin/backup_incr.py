#!/usr/bin/env python

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, PROJECT_ROOT.joinpath('bin').as_posix())
import _venv  # This will activate the venv, if it exists and is not already active

import logging
import os
import shutil
from typing import Iterable

sys.path.append(PROJECT_ROOT.as_posix())
from ds_tools.__version__ import __author_email__, __version__
from ds_tools.argparsing import ArgParser
from ds_tools.core.main import wrap_main
from ds_tools.fs.copy import copy_file
from ds_tools.fs.paths import iter_sorted_files
from ds_tools.logging import init_logging
from ds_tools.output.formatting import readable_bytes

log = logging.getLogger(__name__)
IGNORE_FILES = {'Thumbs.db'}
IGNORE_DIRS = {'__pycache__', '.git', '.idea'}


def parser():
    parser = ArgParser(description='Incremental Backup Tool')
    parser.add_argument('source', metavar='PATH', help='The file to backup')
    parser.add_argument('dest_dir', metavar='PATH', help='The directory in which backups should be stored')
    parser.add_argument('--last_dirs', nargs='+', metavar='PATH', help='One or more previous backup directories')

    options = parser.add_argument_group('Behavior Options')
    options.add_argument('--ignore_files', nargs='+', help='Add additional file names to be ignored')
    options.add_argument('--ignore_dirs', nargs='+', help='Add additional directory names to be ignored')
    options.add_argument('--follow_links', '-L', action='store_true', help='Follow directory symlinks')

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

    backup_util = BackupUtil(args.source, args.last_dirs, args.dest_dir, args.follow_links, args.dry_run)
    backup_util.backup_files()


class BackupUtil:
    def __init__(self, src: str, last: Iterable[str], dest: str, follow_links: bool, dry_run: bool):
        self.src_root = Path(src).expanduser().resolve()
        self.prv_roots = [Path(p).expanduser().resolve() for p in last] if last else []
        self.new_root = Path(dest).expanduser().resolve()
        self.dry_run = dry_run
        self.follow_links = follow_links
        self._prefix = '[DRY RUN] Would backup' if dry_run else 'Backing up'

    def backup_files(self):
        for src_path, rel_path, adj, size in self.iter_target_files():
            self.backup_file(src_path, rel_path, adj, size)

    def matches_previous_backup(self, src_path: Path, rel_path):
        prv_paths = [path for root in self.prv_roots if (path := root.joinpath(rel_path)).exists()]
        if prv_paths:
            src_stat = src_path.stat()
            for prv_path in reversed(prv_paths):  # More likely to match the latest one, assuming chronological order
                prv_stat = prv_path.stat()
                if src_stat.st_size == prv_stat.st_size and src_stat.st_mtime == prv_stat.st_mtime:
                    return True, src_stat
            return False, src_stat
        return None, None

    def iter_target_files(self):
        for src_path in iter_sorted_files(self.src_root, IGNORE_DIRS, IGNORE_FILES, self.follow_links):
            rel_path = src_path.relative_to(self.src_root)
            matches_previous, src_stat = self.matches_previous_backup(src_path, rel_path)
            if matches_previous:
                log.debug(f'Skipping previously backed up file: {rel_path}')
            else:
                adj = 'new' if matches_previous is None else 'modified'
                yield src_path, rel_path, adj, src_stat or src_path.stat()

    def backup_file(self, src_path: Path, rel_path: Path, adj: str, src_stat: os.stat_result):
        new_path = self.new_root.joinpath(rel_path)
        if new_path.exists():
            log.log(19, f'Skipping {rel_path} because it already exists in {self.new_root}')
        else:
            size = src_stat.st_size
            log.info(f'[{readable_bytes(size):>10s}] {self._prefix} {adj} {rel_path}')
            if not self.dry_run:
                dest_dir = new_path.parent
                if not dest_dir.exists():
                    dest_dir.mkdir(parents=True)

                if size > 536870912:  # 512 MB
                    copy_file(src_path, new_path)  # Show progress
                else:
                    shutil.copy(src_path, new_path)

                shutil.copystat(src_path, new_path)


if __name__ == '__main__':
    main()
