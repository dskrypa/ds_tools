#!/usr/bin/env python

from __future__ import annotations

import logging
from functools import cached_property

from cli_command_parser import Command, Option, Counter, Flag, ParamGroup, SubCommand, main
from cli_command_parser.inputs import Path as IPath, NumRange

from ds_tools.fs.steam import GAME_INFO_MAP, GameFileManager, SaveFileEventHandler

log = logging.getLogger(__name__)

BACKUP_DIR = '~/Games/'


class SaveManagerCLI(Command, option_name_mode='*-'):
    """
    Save File Manager for Steam games

    Backs up save files for games that only support a single file per playthrough.
    """

    sub_cmd = SubCommand()
    game = Option('-g', choices=sorted(GAME_INFO_MAP), required=True, help='The game for which saves should be backed up')
    backup_dir = Option('-b', type=IPath(type='dir'), help='Backup destination directory (default: based on game)')
    steam_id = Option(type=int, help='Numeric Steam user ID (should match a directory in the save dir)')
    verbose = Counter('-v', help='Increase logging verbosity (can specify multiple times)')
    dry_run = Flag('-D', help='Print the actions that would be taken instead of taking them')

    def _init_command_(self):
        from ds_tools.logging import init_logging

        init_logging(self.verbose, log_path=None)

    @cached_property
    def game_file_manager(self) -> GameFileManager:
        return GameFileManager(
            GAME_INFO_MAP[self.game], steam_id=self.steam_id, backup_dir=self.backup_dir, dry_run=self.dry_run
        )


class Watch(SaveManagerCLI, help='Copy single save file backups whenever changes are detected'):
    """
    Watch the save directory and store backups when changes occur.

    Intended for games that use a single save file per player / playthrough.
    """

    def main(self):
        SaveFileEventHandler(self.game_file_manager).run()


class Backup(SaveManagerCLI, help='Copy multiple save files into a compressed backup and cleanup old save files'):
    """
    Compresses all save files from the save directory into a single .tar.zst file in the backup directory, and then
    deletes the oldest subset of the backed up files.  Keeps the 5 most recent save files in the save directory.

    Intended for games that support multiple save files per player / playthrough.
    """

    with ParamGroup('Old File', mutually_exclusive=True):
        keep = Option(
            '-k', type=NumRange(int, min=1), default=5, help='The number of the most recently modified save files to retain'
        )
        keep_all = Flag('-A', help='Keep all old save files (do not send any save files to the trash)')

    def main(self):
        self.game_file_manager.create_backup_archive()
        if not self.keep_all:
            self.game_file_manager.delete_old_save_files(keep=self.keep)


class Cleanup(SaveManagerCLI, help='Compress files already in the backup directory and cleanup the backup directory'):
    """
    Compresses the contents of the backups directory into a single .tar.zst file, and then deletes the contents of the
    backup directory.
    """

    keep_old = Flag('-K', help='Do not send the contents of the backup directory to the trash')

    def main(self):
        self.game_file_manager.compress_loose_backups(cleanup=not self.keep_old)


if __name__ == '__main__':
    main()
