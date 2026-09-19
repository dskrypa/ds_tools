#!/usr/bin/env python

import logging
import os
from functools import cached_property
from pathlib import Path
from hashlib import sha256

from cli_command_parser import Command, Option, Counter, ParamGroup, ParamsMissing, main
from cli_command_parser.inputs import Path as IPath
from watchdog.observers import Observer

from ds_tools.fs.paths import unique_path, path_repr

log = logging.getLogger(__name__)

ON_WINDOWS = os.name == 'nt'
STEAM_WINE_PREFIX_DIR = '~/.local/share/Steam/steamapps/compatdata'
BACKUP_DIR = '~/Games/'

WIN_GAME_PATH_MAP = {
    'Myst': '~/AppData/Local/Myst/Saved/SaveGames',
}
NIX_GAME_PATH_MAP = {
    'Clair Obscur': '1903340/pfx/drive_c/users/steamuser/AppData/Local/Sandfall/Saved/SaveGames',
}


class SaveWatcher(Command, option_name_mode='*-'):
    """
    Game Save File Watcher

    Backs up save files for games that only support a single file per playthrough.
    """

    _GAME_PATH_MAP = WIN_GAME_PATH_MAP if ON_WINDOWS else NIX_GAME_PATH_MAP

    with ParamGroup('Source', required=True):
        src_dir = Option('-src', type=IPath(type='dir', exists=True), help='Save file directory to watch')
        game = Option('-g', choices=sorted(_GAME_PATH_MAP), help='The game for which saves should be backed up')

    backup_dir = Option('-b', type=IPath(type='dir'), help='Backup destination directory (default: based on game)')
    verbose = Counter('-v', help='Increase logging verbosity (can specify multiple times)')

    def _init_command_(self):
        from ds_tools.logging import init_logging

        init_logging(self.verbose, log_path=None)

    @cached_property
    def save_dir(self) -> Path:
        if self.src_dir:
            return self.src_dir

        if ON_WINDOWS:
            return Path(WIN_GAME_PATH_MAP[self.game]).expanduser()

        base_dir = Path(STEAM_WINE_PREFIX_DIR).expanduser().joinpath(NIX_GAME_PATH_MAP[self.game])
        for path in base_dir.iterdir():
            # A numeric subdir is expected for Clair Obscur; this requires updates if other games are different
            if path.is_dir() and path.name.isdigit():
                return path

        raise RuntimeError(f'Unable to find numeric dir inside {path_repr(base_dir)}')

    @cached_property
    def dst_dir(self) -> Path:
        if self.backup_dir:
            return self.backup_dir

        if self.game:
            return Path(BACKUP_DIR).expanduser().joinpath(self.game.replace(' ', '_'))

        raise ParamsMissing(self.__class__.backup_dir, 'backup dir is required when using --src-dir')

    def main(self):
        if self.dst_dir.exists() and not self.dst_dir.is_dir():
            raise ValueError(f'Invalid backup dir: {path_repr(self.dst_dir)} - it is not a directory')

        self.dst_dir.mkdir(parents=True, exist_ok=True)
        if self.save_dir.samefile(self.dst_dir):
            raise ValueError('The backup dir must be different from the save dir')

        FSEventHandler(self.save_dir, self.dst_dir).run()


class FSEventHandler:
    def __init__(self, save_dir: Path, backup_dir: Path):
        self.save_dir = save_dir
        self.backup_dir = backup_dir
        self.observer = Observer()
        self.observer.schedule(self, save_dir.as_posix())
        self.last_hashes = {}

    def run(self):
        log.info(f'Watching {self.save_dir.as_posix()} with observer={self.observer}')
        self.observer.start()
        try:
            while True:
                self.observer.join(0.5)
        except KeyboardInterrupt:
            self.observer.stop()
            self.observer.join()

    def dispatch(self, event):
        what = 'directory' if event.is_directory else 'file'
        path = Path(event.src_path).resolve()
        # path_match = path == self.path
        # if path_match and event.event_type == 'modified':
        if event.event_type == 'modified' and not event.is_directory:
            log.log(11, f'Detected modified event for {path.as_posix()}')
            self.save_backup(path)
        else:
            # verb, level = ('Detected', 11) if path_match else ('Ignoring', 10)
            verb, level = 'Detected', 11
            suffix = f' -> {event.dest_path}' if event.event_type == 'moved' else ''
            log.log(level, f'{verb} {event.event_type} event for {what}: {path.as_posix()}{suffix}')

    def save_backup(self, path: Path):
        data = path.read_bytes()
        if not data:
            log.log(11, 'Skipping backup of empty file')
            return

        data_hash = sha256(data).hexdigest()
        last_hash = self.last_hashes.get(path.name)

        if data_hash != last_hash:
            log.debug(f'Data changed for file={path.name} - old={last_hash} new={data_hash}')
            self.last_hashes[path.name] = data_hash
            dest_path = unique_path(self.backup_dir, path.stem, path.suffix, add_date=True)
            log.info(f'Saving backup to {dest_path.as_posix()}')
            dest_path.write_bytes(data)
        else:
            log.log(11, f'There were no changes to {path_repr(path)} - sha256={data_hash}')


if __name__ == '__main__':
    main()
