#!/usr/bin/env python

from __future__ import annotations

import logging
import re
from datetime import datetime
from functools import cached_property
from pathlib import Path
from tarfile import TarFile

from cli_command_parser import Command, SubCommand, Flag, Counter, main
from cli_command_parser.inputs import Path as IPath
from send2trash import send2trash
from zstandard import ZstdCompressor

from ds_tools.fs.paths import unique_path, path_repr
from ds_tools.output.prefix import LoggingPrefix

log = logging.getLogger(__name__)

DIR = IPath(type='dir', exists=True)

DEFAULT_STEAM_DIR = '~/.local/share/Steam'
FF7_REBIRTH_C_DRIVE = 'steamapps/compatdata/2909400/pfx/drive_c'
FF7_REBIRTH_SAVE_DIR = 'users/steamuser/Documents/My Games/FINAL FANTASY VII REBIRTH/Steam'

BACKUP_DIR = '~/Games/FF7_Rebirth'


# region CLI Commands


class SaveManagerCLI(Command):
    sub_cmd = SubCommand()
    verbose = Counter('-v', help='Increase logging verbosity (can specify multiple times)')
    dry_run = Flag('-D', help='Print the actions that would be taken instead of taking them')

    def _init_command_(self):
        from ds_tools.logging import init_logging

        init_logging(self.verbose)

    @cached_property
    def lp(self) -> LoggingPrefix:
        return LoggingPrefix(self.dry_run)

    @cached_property
    def save_files_dir(self) -> SaveFilesDir:
        return SaveFilesDir(dry_run=self.dry_run)


class Backup(SaveManagerCLI, help='Backup save files'):
    keep_old = Flag('-K', help='If specified, old save files will not be moved to the trash (default: move to trash)')

    def main(self):
        self.save_files_dir.create_backup(not self.keep_old)


# endregion


# region Helpers


class SaveFilesDir:
    _name_pat = re.compile(r'^ff7rebirth0(\d\d)\.sav$')
    steam_dir: Path

    def __init__(
        self,
        *,
        steam_dir: Path | None = None,
        steam_id: int | str | None = None,
        backup_dir: Path | None = None,
        dry_run: bool = False,
    ):
        self.steam_dir = steam_dir or Path(DEFAULT_STEAM_DIR).expanduser()
        self.wine_root = self.steam_dir.joinpath(FF7_REBIRTH_C_DRIVE)
        if steam_id:
            self.save_dir = self.wine_root.joinpath(FF7_REBIRTH_SAVE_DIR, steam_id)
        else:
            steam_save_dir: Path = self.wine_root.joinpath(FF7_REBIRTH_SAVE_DIR)
            self.save_dir = next(p for p in steam_save_dir.iterdir() if p.is_dir())

        self.backup_dir = backup_dir or Path(BACKUP_DIR).expanduser()
        self.dry_run = dry_run
        self.lp = LoggingPrefix(dry_run)

    def create_backup(self, delete_old: bool = True):
        self._create_backup()
        if delete_old:
            self.delete_old_save_files()

    def _create_backup(self):
        bkp_path = unique_path(self.backup_dir, 'ff7rebirth_saves', '.tar.zst', add_date=True)
        log.info(f'{self.lp.create} backup: {path_repr(bkp_path)}')
        if self.dry_run:
            return

        bkp_path.parent.mkdir(parents=True, exist_ok=True)
        with bkp_path.open('wb') as f, ZstdCompressor(9).stream_writer(f) as zf, TarFile(bkp_path.name, 'w', zf) as tf:
            for path in self.save_dir.iterdir():
                log.log(19, f'Adding {path.name} to archive...')
                tf.add(path, path.name)

    def delete_old_save_files(self, keep: int = 5):
        paths = sorted(
            (p.stat().st_mtime, p)
            for p in self.save_dir.iterdir()
            if (m := self._name_pat.match(p.name)) and m.group(1) != '00'
        )
        if (to_rm := len(paths) - keep) <= 0:
            log.info('There are no old save files to delete')
            return

        log.info(f'{self.lp.send} {to_rm}/{len(paths)} old save files to the trash...')
        for mod_time, path in paths[:to_rm]:
            log.info(f'{self.lp.send} to trash: {path.name} [{datetime.fromtimestamp(mod_time).isoformat(" ")}]')
            if not self.dry_run:
                send2trash(path)

        for mod_time, path in paths[to_rm:]:
            log.info(f'Keeping {path.name} [{datetime.fromtimestamp(mod_time).isoformat(" ")}]')

# endregion


if __name__ == '__main__':
    main()
