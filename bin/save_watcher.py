#!/usr/bin/env python

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, PROJECT_ROOT.joinpath('bin').as_posix())
import _venv  # This will activate the venv, if it exists and is not already active

import logging
from hashlib import sha256

from watchdog.observers import Observer

sys.path.append(PROJECT_ROOT.as_posix())
from ds_tools.__version__ import __author_email__, __version__
from ds_tools.argparsing import ArgParser
from ds_tools.core.main import wrap_main
from ds_tools.fs.paths import unique_path
from ds_tools.logging import init_logging

log = logging.getLogger(__name__)


def parser():
    parser = ArgParser(description='Nier Replicant ver.1.22474487139... Save File Watcher')
    parser.add_argument('--path', '-p', help='Save file path to watch')
    parser.add_argument('--backups', '-b', metavar='PATH', help='Path to the directory in which backups should be saved (default: same dir as save files)')
    parser.include_common_args('verbosity')
    return parser


@wrap_main
def main():
    args = parser().parse_args()
    init_logging(args.verbose, log_path=None)

    save_dir = Path(args.path or '~/AppData/Local/Myst/Saved/SaveGames').expanduser().resolve()
    backup_dir = Path(args.backups).expanduser().resolve() if args.backups else save_dir.parent.joinpath('SaveBackups')
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
            dest_path = unique_path(self.backup_dir, path.stem, path.suffix)
            log.info(f'Saving backup to {dest_path.as_posix()}')
            dest_path.write_bytes(data)
        else:
            log.log(11, f'There were no changes to {path.as_posix()} - sha256={data_hash}')


if __name__ == '__main__':
    main()
