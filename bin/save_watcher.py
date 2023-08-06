#!/usr/bin/env python

import logging
from pathlib import Path
from hashlib import sha256

from cli_command_parser import Command, Option, Counter, main, inputs
from watchdog.observers import Observer

from ds_tools.__version__ import __author_email__, __version__  # noqa
from ds_tools.fs.paths import unique_path

log = logging.getLogger(__name__)


class SaveWatcher(Command, description='Game Save File Watcher'):
    path = Option('-p', help='Save file path to watch')
    backups = Option('-b', type=inputs.Path(type='dir'), help='Path to the directory in which backups should be saved (default: same dir as save files)')
    verbose = Counter('-v', help='Increase logging verbosity (can specify multiple times)')

    def _init_command_(self):
        from ds_tools.logging import init_logging

        init_logging(self.verbose, log_path=None)

    def main(self):
        save_dir = Path(self.path or '~/AppData/Local/Myst/Saved/SaveGames').expanduser().resolve()
        backup_dir = self.backups or save_dir.parent.joinpath('SaveBackups')
        if save_dir.samefile(backup_dir):
            raise ValueError('The backup dir must be different from the save dir')
        if backup_dir.exists() and not backup_dir.is_dir():
            raise ValueError(f'Invalid backup_dir={backup_dir.as_posix()} - it is not a directory')
        elif not backup_dir.exists():
            log.debug(f'Creating backup_dir={backup_dir.as_posix()}')
            backup_dir.mkdir(parents=True)

        FSEventHandler(save_dir, backup_dir).run()


class FSEventHandler:
    def __init__(self, save_dir: Path, backup_dir: Path):
        self.save_dir = save_dir
        self.backup_dir = backup_dir
        self.observer = Observer()
        self.observer.schedule(self, save_dir.as_posix())
        self.last_hash = None

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
        if event.event_type == 'modified':
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
        if data_hash != self.last_hash:
            log.debug(f'Data changed - old={self.last_hash} new={data_hash}')
            self.last_hash = data_hash
            dest_path = unique_path(self.backup_dir, path.stem, path.suffix, add_date=True)
            log.info(f'Saving backup to {dest_path.as_posix()}')
            dest_path.write_bytes(data)
        else:
            log.log(11, f'There were no changes to {path.as_posix()} - sha256={data_hash}')


if __name__ == '__main__':
    main()
