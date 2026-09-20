#!/usr/bin/env python

from __future__ import annotations

import logging
from functools import cached_property
from pathlib import Path

from cli_command_parser import Command, Option, Counter, ParamGroup, ParamsMissing, main
from cli_command_parser.inputs import Path as IPath

from ds_tools.fs.paths import path_repr
from ds_tools.fs.steam import GAME_INFO_MAP, GameInfo, SaveDir, SaveFileEventHandler

log = logging.getLogger(__name__)

BACKUP_DIR = '~/Games/'


class SaveWatcher(Command, option_name_mode='*-'):
    """
    Game Save File Watcher

    Backs up save files for games that only support a single file per playthrough.
    """

    with ParamGroup('Source', required=True):
        src_dir = Option('-src', type=IPath(type='dir', exists=True), help='Save file directory to watch')
        game = Option('-g', choices=sorted(GAME_INFO_MAP), help='The game for which saves should be backed up')

    backup_dir = Option('-b', type=IPath(type='dir'), help='Backup destination directory (default: based on game)')
    steam_id = Option(type=int, help='Numeric Steam user ID (should match a directory in the save dir)')
    verbose = Counter('-v', help='Increase logging verbosity (can specify multiple times)')

    def _init_command_(self):
        from ds_tools.logging import init_logging

        init_logging(self.verbose, log_path=None)

    @cached_property
    def game_info(self) -> GameInfo:
        return GAME_INFO_MAP[self.game]

    @cached_property
    def dst_dir(self) -> Path:
        if self.backup_dir:
            return self.backup_dir

        if self.game:
            short_name = self.game_info.short_name or self.game_info.name
            return Path(BACKUP_DIR).expanduser().joinpath(short_name.replace(' ', '_'))

        raise ParamsMissing(self.__class__.backup_dir, 'backup dir is required when using --src-dir')

    def main(self):
        if self.dst_dir.exists() and not self.dst_dir.is_dir():
            raise ValueError(f'Invalid backup dir: {path_repr(self.dst_dir)} - it is not a directory')

        save_dir = SaveDir(self.game_info, self.steam_id).path if self.game else self.src_dir
        SaveFileEventHandler(save_dir, self.dst_dir).run()


if __name__ == '__main__':
    main()
