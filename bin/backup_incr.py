#!/usr/bin/env python

import logging
import os
import shutil
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Iterable, Optional

from cli_command_parser import Command, SubCommand, ParamGroup, Positional, Option, Flag, Counter, main

from ds_tools.__version__ import __author_email__, __version__  # noqa
from ds_tools.fs.copy import copy_file
from ds_tools.fs.paths import iter_sorted_files
from ds_tools.output.formatting import readable_bytes

log = logging.getLogger(__name__)
IGNORE_FILES = {'Thumbs.db', '.windows'}
IGNORE_DIRS = {'__pycache__', '.git', '.idea'}


class BackupUtilCLI(Command, description='Incremental Backup Tool'):
    action = SubCommand()
    verbose = Counter('-v', help='Increase logging verbosity (can specify multiple times)')
    dry_run = Flag('-D', help='Print the actions that would be taken instead of taking them')

    with ParamGroup(description='Behavior Options'):
        ignore_files = Option(nargs='+', help='Add additional file names to be ignored')
        ignore_dirs = Option(nargs='+', help='Add additional directory names to be ignored')
        follow_links = Flag('-L', help='Follow directory symlinks')

    def _init_command_(self):
        from ds_tools.logging import init_logging

        init_logging(self.verbose)
        if self.ignore_files:
            IGNORE_FILES.update(self.ignore_files)
        if self.ignore_dirs:
            IGNORE_DIRS.update(self.ignore_dirs)


class Backup(BackupUtilCLI, help='Create an incremental backup'):
    source = Positional(metavar='PATH', help='The file to backup')
    dest_dir = Positional(metavar='PATH', help='The directory in which backups should be stored')
    last_dirs = Option(metavar='PATH', nargs='+', help='One or more previous backup directories')

    def main(self):
        BackupUtil(self.source, self.last_dirs, self.dest_dir, self.follow_links, self.dry_run).process_files()


class Rebuild(BackupUtilCLI, help='Rebuild a remote tree from local incremental backups'):
    remote = Positional(help='A remote directory')
    destination = Positional(help='The local destination directory')
    sources = Positional(nargs='+', help='Local incremental backup directories')

    def main(self):
        RebuildUtil(self.remote, self.destination, self.sources, self.follow_links, self.dry_run).process_files()


class CopyUtil(ABC):
    def __init__(self, dest: str, follow_links: bool, dry_run: bool):
        self.dst_root = Path(dest).expanduser().resolve()
        self.dry_run = dry_run
        self.follow_links = follow_links
        self._prefix = '[DRY RUN] Would copy' if dry_run else 'Copying'

    def _log_copy(self, rel_path: Path, size: int, adj: Optional[str] = None):
        if adj:
            log.info(f'[{readable_bytes(size):>11s}] {self._prefix} {adj} {rel_path}')
        else:
            log.info(f'[{readable_bytes(size):>11s}] {self._prefix} {rel_path}')

    def copy_file(self, src_path: Path, rel_path: Path, src_stat: os.stat_result, adj: Optional[str] = None):
        dst_path = self.dst_root.joinpath(rel_path)
        if dst_path.exists():
            log.log(19, f'Skipping {rel_path} because it already exists in {self.dst_root}')
        else:
            size = src_stat.st_size
            self._log_copy(rel_path, size, adj)
            if not self.dry_run:
                dest_dir = dst_path.parent
                if not dest_dir.exists():
                    dest_dir.mkdir(parents=True)

                try:
                    if size > 536870912:  # 512 MB
                        copy_file(src_path, dst_path)  # Show progress
                    else:
                        shutil.copy(src_path, dst_path)
                except BaseException:
                    if dst_path.exists():
                        log.warning(f'Deleting incomplete {dst_path}')
                        dst_path.unlink()
                    raise

                shutil.copystat(src_path, dst_path)

    def process_files(self):
        for args in self.iter_target_files():
            self.copy_file(*args)

    @abstractmethod
    def iter_target_files(self) -> tuple:
        return NotImplemented


class RebuildUtil(CopyUtil):
    def __init__(self, remote: str, dest: str, sources: Iterable[str], follow_links: bool, dry_run: bool):
        super().__init__(dest, follow_links, dry_run)
        self.rmt_root = Path(remote).expanduser().resolve()
        self.src_roots = [Path(p).expanduser().resolve() for p in sorted(sources, reverse=True)]
        if any(not v for v in (self.rmt_root, self.dst_root, self.src_roots)):
            raise ValueError('remote, destination, and sources are all required')
        log.debug('Local source order:\n{}'.format('\n'.join(map(Path.as_posix, self.src_roots))))

    def iter_target_files(self):
        rmt_root = self.rmt_root
        for rmt_path in iter_sorted_files(rmt_root, IGNORE_DIRS, IGNORE_FILES, self.follow_links):
            rel_path = rmt_path.relative_to(rmt_root)
            if lcl_path := next((path for root in self.src_roots if (path := root.joinpath(rel_path)).exists()), None):
                yield lcl_path, rel_path, lcl_path.stat()
            else:
                log.warning(f'Could not find local version of {rmt_path}', extra={'color': 'red'})


class BackupUtil(CopyUtil):
    def __init__(self, src: str, last: Iterable[str], dest: str, follow_links: bool, dry_run: bool):
        super().__init__(dest, follow_links, dry_run)
        self.src_root = Path(src).expanduser().resolve()
        self.prv_roots = [Path(p).expanduser().resolve() for p in last] if last else []
        self._prefix = '[DRY RUN] Would backup' if dry_run else 'Backing up'

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
        for src_path in iter_sorted_files(self.src_root, IGNORE_DIRS, IGNORE_FILES, follow_links=self.follow_links):
            rel_path = src_path.relative_to(self.src_root)
            matches_previous, src_stat = self.matches_previous_backup(src_path, rel_path)
            if matches_previous:
                log.debug(f'Skipping previously backed up file: {rel_path}')
            else:
                adj = 'new' if matches_previous is None else 'modified'
                yield src_path, rel_path, src_stat or src_path.stat(), adj


if __name__ == '__main__':
    main()
