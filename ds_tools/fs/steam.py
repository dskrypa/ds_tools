"""
Utilities for working with files associated with games installed via Steam.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime
from functools import cached_property
from hashlib import sha256
from pathlib import Path
from tarfile import TarFile
from typing import TYPE_CHECKING, Iterator, Self

from send2trash import send2trash
from watchdog.observers import Observer
from zstandard import ZstdCompressor

from ds_tools.output.prefix import DryRunMixin
from .paths import unique_path, path_repr

if TYPE_CHECKING:
    from watchdog.events import FileSystemEvent

__all__ = ['GAMES', 'GAME_INFO_MAP', 'GameInfo', 'GameFileManager', 'SaveFileEventHandler']
log = logging.getLogger(__name__)

_ON_WINDOWS = os.name == 'nt'
STEAM_WINE_PREFIX_DIR = '~/.local/share/Steam/steamapps/compatdata'
DEFAULT_BACKUP_BASE_DIR = '~/Games/'


# region Game Info

@dataclass
class GameInfo:
    name: str
    app_id: int
    save_dir: str
    short_name: str = ''
    file_name_pat: str | None = None

    def __post_init__(self):
        if not self.short_name:
            self.short_name = self.name

    @cached_property
    def name_for_files(self) -> str:
        return self.short_name.replace(' ', '_')

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
    GameInfo(
        'FINAL FANTASY VII REBIRTH', 2909400, '{home}/Documents/My Games/{name}/Steam/{steam_id}',
        short_name='FF7 Rebirth', file_name_pat=r'^ff7rebirth0(\d\d)\.sav$',
    ),
    GameInfo('Myst', 1255560, '{home}/AppData/Local/Myst/Saved/SaveGames'),
    GameInfo(
        'Clair Obscur: Expedition 33', 1903340, '{home}/AppData/Local/Sandfall/Saved/SaveGames/{steam_id}',
        short_name='Clair Obscur',
    ),
]

GAME_INFO_MAP: dict[str, GameInfo] = {gi.short_name or gi.name: gi for gi in GAMES}

# endregion


class GameFileManager(DryRunMixin):
    def __init__(
        self,
        info: GameInfo,
        *,
        steam_id: int | str | None = None,
        backup_dir: Path | None = None,
        dry_run: bool = False,
    ):
        self.info = info
        self.dry_run = dry_run
        self._last_hashes = {}
        self.save_dir = info.get_save_dir(steam_id)
        self.backup_dir = backup_dir or Path(DEFAULT_BACKUP_BASE_DIR).expanduser().joinpath(info.name_for_files)
        if self.backup_dir.exists() and not self.backup_dir.is_dir():
            raise ValueError(f'Invalid backup dir: {path_repr(self.backup_dir)} - it is not a directory')
        if not self.dry_run:
            self.backup_dir.mkdir(parents=True, exist_ok=True)

    def compress_loose_backups(self, cleanup: bool = True, *, level: int = 9) -> Path | None:
        """
        Compress loose backup files that were copied via file watcher to the backup directory, then delete the loose
        backup files.

        :param cleanup: Whether the loose backup files should be deleted.
        :param level: Compression level to use
        :return: The path of the archive that was created
        """
        if group := FileGroup.from_dir(self.backup_dir, dry_run=self.dry_run):
            range_str = group.get_time_range_str(from_names=True)
            bkp_path = unique_path(self.backup_dir.parent, f'{self.info.name_for_files}_saves_{range_str}', '.tar.zst')
            group.create_tar_zst(bkp_path, level=level, rm_originals=cleanup)
            return bkp_path

        log.info(f'Skipping archive creation - no files exist in {group}')
        return None

    # region Single Save File Methods

    def maybe_save_backup(self, path: Path):
        """
        Intended to be called by the ``dispatch`` method of a Watchdog Observer when a monitored save file has been
        modified.

        :param path: Path to a file for which a change event was triggered
        """
        data = path.read_bytes()
        if not data:
            log.log(11, 'Skipping backup of empty file')
            return

        data_hash = sha256(data).hexdigest()
        last_hash = self._last_hashes.get(path.name)

        if data_hash != last_hash:
            log.debug(f'Data changed for file={path.name} - old={last_hash} new={data_hash}')
            self._last_hashes[path.name] = data_hash
            dest_path = unique_path(self.backup_dir, path.stem, path.suffix, add_date=True, add_time=True)
            log.info(f'{self.lp.save} backup to {dest_path.as_posix()}')
            if not self.dry_run:
                dest_path.write_bytes(data)
        else:
            log.log(11, f'There were no changes to {path_repr(path)} - sha256={data_hash}')

    # endregion

    # region Multiple Save File Methods

    def create_archive_from_source(self, *, level: int = 9) -> Path:
        """
        Compress loose save files from the original save directory, and store the backup archive in the backup dir.

        :param level: Compression level to use
        :return: The path of the archive that was created
        """
        group = FileGroup.from_dir(self.save_dir, dry_run=self.dry_run)
        range_str = group.get_time_range_str(from_names=True)
        bkp_path = unique_path(self.backup_dir, f'{self.info.name_for_files}_saves_{range_str}', '.tar.zst')
        group.create_tar_zst(bkp_path, level=level)
        return bkp_path

    def delete_old_save_files(self, keep: int = 5):
        if not self.info.file_name_pat:
            raise UnsupportedGameError(f'Deletion of old save files by age is not supported for {self.info.name}')

        name_match = re.compile(self.info.file_name_pat).match

        group = FileGroup(
            # This regex group logic may need to change for other games
            [p for p in self.save_dir.iterdir() if (m := name_match(p.name)) and m.group(1) != '00'],
            dry_run=self.dry_run,
            parent=self.save_dir,
        )
        group.send_old_to_trash(keep=keep)

    # endregion


class FileGroup(DryRunMixin):
    def __init__(self, paths: list[Path], dry_run: bool = False, parent: Path | None = None):
        self.parent = parent
        self.paths = paths
        self.dry_run = dry_run

    @classmethod
    def from_dir(cls, path: Path, dry_run: bool = False) -> Self:
        return cls(list(path.iterdir()), dry_run=dry_run, parent=path)

    def create_tar_zst(self, path: Path, *, level: int = 9, rm_originals: bool = False):
        """
        :param path: The path of the archive to create
        :param level: The zstandard compression level to use (1-22)
        :param rm_originals: Whether the paths in this group should be removed (sent to the trash) after adding them to
          the archive.
        """
        if not self.paths:
            log.info(f'Skipping archive creation - no files exist in {self}')
            return

        log.info(f'{self.lp.create} archive: {path_repr(path)}')
        if self.dry_run:
            return

        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('wb') as f, ZstdCompressor(level).stream_writer(f) as zf, TarFile(path.name, 'w', zf) as tf:
            for src_path in self.paths:
                log.log(19, f'Adding {src_path.name} to archive...')
                tf.add(src_path, src_path.name)

        if rm_originals:
            self.send_all_to_trash()

    def send_all_to_trash(self):
        for path in self.paths:
            log.info(f'{self.lp.send} to trash: {path_repr(path)}')
            if not self.dry_run:
                send2trash(path)

    def send_old_to_trash(self, keep: int = 5):
        """
        :param keep: The number of latest recently modified files to keep
        """
        paths = sorted((p.stat().st_mtime, p) for p in self.paths)
        if (to_rm := len(paths) - keep) <= 0:
            log.info(f'There are no old save files to delete in {self}')
            return

        log.info(f'{self.lp.send} {to_rm}/{len(paths)} old save files to the trash...')
        for mod_time, path in paths[:to_rm]:
            log.info(f'{self.lp.send} to trash: {path_repr(path)} [{datetime.fromtimestamp(mod_time).isoformat(" ")}]')
            if not self.dry_run:
                send2trash(path)

        for mod_time, path in paths[to_rm:]:
            log.info(f'Keeping {path_repr(path)} [{datetime.fromtimestamp(mod_time).isoformat(" ")}]')

    # region Time Range

    def get_time_range_str(self, from_names: bool = False, verbose: bool = False) -> str:
        """
        Uses :meth:`.get_time_range` to get the earliest and latest times from the files in this group, then formats
        a concise representation of the date and/or time range.

        :param from_names: Whether the dates should be parsed from file names (falls back to last modified time).  If
          False, then last modified time is used for all files.
        :param verbose: Whether the full date and time should be included for both earliest and latest times
        :return: The formatted time range
        """
        earliest, latest = self.get_time_range(from_names)
        if verbose:
            return f'{earliest:%Y-%m-%d_%H-%M-%S}--{latest:%Y-%m-%d_%H-%M-%S}'
        elif earliest.date() == latest.date():
            return f'{earliest:%Y-%m-%d_%H-%M-%S}--{latest:%H-%M-%S}'
        else:
            return f'{earliest:%Y-%m-%d}--{latest:%Y-%m-%d}'

    def get_time_range(self, from_names: bool = False) -> tuple[datetime, datetime]:
        times = self._get_times(from_names)
        return min(times), max(times)

    def _get_times(self, from_names: bool = False) -> set[datetime]:
        if not from_names:
            return {datetime.fromtimestamp(path.stat().st_mtime) for path in self.paths}

        date_pat = r'\d{4}-(?:1[01]|0\d)-[0-3]\d'
        time_pat = r'(?:[01]\d|2[0-4])-[0-5]\d-[0-5]\d'

        date_suffix = re.compile(rf'({date_pat})(?:-\d+)?$')
        dt_maybe_suffix = re.compile(rf'({date_pat}_{time_pat})(?:-\d+)?$')
        date_with_time_range = re.compile(rf'({date_pat})_({time_pat})--({time_pat})')
        date_range = re.compile(rf'({date_pat})--({date_pat})')
        full_dt_range = re.compile(rf'({date_pat}_{time_pat})--({date_pat}_{time_pat})')

        dt_format = '%Y-%m-%d_%H-%M-%S'
        times = set()
        for path in self.paths:
            if m := dt_maybe_suffix.match(path.stem):
                times.add(datetime.strptime(m.group(1), dt_format))
            elif m := date_with_time_range.search(path.stem):
                date_part = m.group(1)
                times.add(datetime.strptime(f'{date_part}_{m.group(2)}', dt_format))
                times.add(datetime.strptime(f'{date_part}_{m.group(3)}', dt_format))
            elif m := full_dt_range.search(path.stem):
                times.update(datetime.strptime(g, dt_format) for g in m.groups())
            elif m := date_range.search(path.stem):
                times.update(datetime.strptime(g, '%Y-%m-%d') for g in m.groups())
            elif m := date_suffix.match(path.stem):
                times.add(datetime.strptime(m.group(1), '%Y-%m-%d'))
            else:
                log.debug(f'No date/time match found for {path_repr(path)} - using last modified time instead')
                times.add(datetime.fromtimestamp(path.stat().st_mtime))

        return times

    # endregion

    # region Dunder Methods

    def __bool__(self) -> bool:
        return bool(self.paths)

    def __len__(self) -> int:
        return len(self.paths)

    def __iter__(self) -> Iterator[Path]:
        yield from self.paths

    def __str__(self) -> str:
        return path_repr(self.parent) if self.parent else repr(self)

    def __repr__(self) -> str:
        parent = path_repr(self.parent) if self.parent else None
        return f'<{self.__class__.__name__}[{len(self.paths)} paths, {parent=}, dry_run={self.dry_run}]>'

    # endregion


class SaveFileEventHandler:
    def __init__(self, gfm: GameFileManager):
        self.gfm = gfm
        if gfm.save_dir.samefile(gfm.backup_dir):  # This is after backup manager init to ensure backup_dir exists
            raise ValueError(
                'The backup directory must be different from the monitored save directory, otherwise the creation of'
                ' backup files would trigger monitored file change events that would each cause an additional backup'
                ' to be created in an endless loop, which would eventually fill the disk.'
            )

        self.observer = Observer()
        self.observer.schedule(self, gfm.save_dir.as_posix())

    def run(self):
        log.info(f'Watching {path_repr(self.gfm.save_dir)} with observer={self.observer}')
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
            self.gfm.maybe_save_backup(path)
        else:
            # verb, level = ('Detected', 11) if path_match else ('Ignoring', 10)
            verb, level = 'Detected', 11
            suffix = f' -> {event.dest_path}' if event.event_type == 'moved' else ''
            log.log(level, f'{verb} {event.event_type} event for {what}: {path_repr(path)}{suffix}')


class UnsupportedGameError(Exception):
    pass
