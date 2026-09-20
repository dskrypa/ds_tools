"""
Utilities for working with files associated with games installed via Steam.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import TYPE_CHECKING

from watchdog.observers import Observer

from .paths import unique_path, path_repr

if TYPE_CHECKING:
    from watchdog.events import FileSystemEvent

__all__ = ['GAMES', 'GAME_INFO_MAP', 'GameInfo', 'SaveDir', 'SaveFileBackupManager', 'SaveFileEventHandler']
log = logging.getLogger(__name__)

_ON_WINDOWS = os.name == 'nt'
STEAM_WINE_PREFIX_DIR = '~/.local/share/Steam/steamapps/compatdata'


# region Game Info

@dataclass
class GameInfo:
    name: str
    app_id: int
    save_dir: str
    short_name: str | None = None

    def get_save_dir(self, steam_id: int | str | None = None) -> Path:
        if _ON_WINDOWS:
            home = Path.home()
        else:
            home = Path(STEAM_WINE_PREFIX_DIR).expanduser().joinpath(f'{self.app_id}/pfx/drive_c/users/steamuser')

        if not steam_id and '{steam_id}' in self.save_dir:
            steam_id = self._find_steam_id(home.as_posix())

        return Path(self.save_dir.format(home=home.as_posix(), name=self.name, steam_id=steam_id))

    def _find_steam_id(self, home: str) -> str:
        prefix, suffix = self.save_dir.split('{steam_id}', 1)
        if not prefix.endswith('/'):
            raise ValueError(f'Unexpected save_dir format={self.save_dir!r} - a specific steam_id is required')

        base_dir = Path(prefix.format(home=home, name=self.name))
        if steam_id := next((p.name for p in base_dir.iterdir() if p.is_dir() and p.name.isdigit()), None):
            return steam_id
        raise ValueError(f'No steam_id dir found in {base_dir.as_posix()} - a specific steam_id is required')


GAMES = [
    GameInfo('FINAL FANTASY VII REBIRTH', 2909400, '{home}/Documents/My Games/{name}/Steam/{steam_id}', 'FF7 Rebirth'),
    GameInfo('Myst', 1255560, '{home}/AppData/Local/Myst/Saved/SaveGames'),
    GameInfo('Clair Obscur: Expedition 33', 1903340, '{home}/AppData/Local/Sandfall/Saved/SaveGames/{steam_id}', 'Clair Obscur'),
]

GAME_INFO_MAP: dict[str, GameInfo] = {gi.short_name or gi.name: gi for gi in GAMES}

# endregion


class SaveDir:
    def __init__(self, game_info: GameInfo, steam_id: int | str | None = None):
        self.game_info = game_info
        self.path = game_info.get_save_dir(steam_id)


class SaveFileBackupManager:
    def __init__(self, backup_dir: Path):
        backup_dir.mkdir(parents=True, exist_ok=True)
        self.backup_dir = backup_dir
        self.last_hashes = {}

    def maybe_save_backup(self, path: Path):
        data = path.read_bytes()
        if not data:
            log.log(11, 'Skipping backup of empty file')
            return

        data_hash = sha256(data).hexdigest()
        last_hash = self.last_hashes.get(path.name)

        if data_hash != last_hash:
            log.debug(f'Data changed for file={path.name} - old={last_hash} new={data_hash}')
            self.last_hashes[path.name] = data_hash
            dest_path = unique_path(self.backup_dir, path.stem, path.suffix, add_date=True, add_time=True)
            log.info(f'Saving backup to {dest_path.as_posix()}')
            dest_path.write_bytes(data)
        else:
            log.log(11, f'There were no changes to {path_repr(path)} - sha256={data_hash}')


class SaveFileEventHandler:
    def __init__(self, save_dir: Path, backup_dir: Path):
        self.save_dir = save_dir
        self.backup_mgr = SaveFileBackupManager(backup_dir)
        if save_dir.samefile(backup_dir):  # This is after backup manager init to ensure backup_dir exists
            raise ValueError(
                'The backup directory must be different from the monitored save directory, otherwise the creation of'
                ' backup files would trigger monitored file change events that would each cause an additional backup'
                ' to be created in an endless loop, which would eventually fill the disk.'
            )

        self.observer = Observer()
        self.observer.schedule(self, save_dir.as_posix())

    def run(self):
        log.info(f'Watching {path_repr(self.save_dir)} with observer={self.observer}')
        self.observer.start()
        try:
            while True:
                self.observer.join(0.5)
        except KeyboardInterrupt:
            self.observer.stop()
            self.observer.join()

    def dispatch(self, event: FileSystemEvent):
        what = 'directory' if event.is_directory else 'file'
        path = Path(event.src_path).resolve()  # type: ignore
        if event.event_type == 'modified' and not event.is_directory:
            log.log(11, f'Detected modified event for {path_repr(path)}')
            self.backup_mgr.maybe_save_backup(path)
        else:
            # verb, level = ('Detected', 11) if path_match else ('Ignoring', 10)
            verb, level = 'Detected', 11
            suffix = f' -> {event.dest_path}' if event.event_type == 'moved' else ''
            log.log(level, f'{verb} {event.event_type} event for {what}: {path_repr(path)}{suffix}')
