#!/usr/bin/env python

import logging
import re
import tarfile
from argparse import ArgumentParser
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple

log = logging.getLogger(__name__)


def parser():
    parser = ArgumentParser(description='Plex Backup Utility')
    parser.add_argument('source', help='Path to the Plex Media Server directory to be backed up')
    parser.add_argument('--destination', '-d', metavar='PATH', default='.', help='Path in which the backup file should be written')
    parser.add_argument('--mode', '-m', choices=('gz', 'bz2', 'xz'), help='Compression mode (default: gz or based on destination extension)')
    parser.add_argument('--level', '-L', type=int, default=9, help='Compression level (default: %(default)s)')
    parser.add_argument('--verbose', '-v', action='count', default=0, help='Increase logging verbosity (can specify multiple times)')
    return parser


def main():
    args = parser().parse_args()

    level = (logging.INFO - args.verbose) if args.verbose < 2 else logging.DEBUG
    if level == logging.DEBUG:
        logging.basicConfig(level=level, format='%(asctime)s %(levelname)s %(name)s %(lineno)d %(message)s')
    else:
        logging.basicConfig(level=level, format='%(message)s')

    source = normalize_source(args.source)
    dest, mode = prepare_dest(args.destination, args.mode)
    backup_plex(source, dest, mode, args.level)


def backup_plex(source: Path, dest: Path, mode: str, level: int):
    db_backup_match = re.compile(r'.db-\d{4}-\d{2}-\d{2}').match
    if level < 1:
        if len(dest.suffixes) > 1:
            dest = dest.with_suffix('')
        log.info(f'Saving backup to {dest} with compression=None')
        mode = 'w'
    else:
        log.info(f'Saving backup to {dest} with compression={mode}')
        mode = f'w:{mode}'

    with tarfile.open(dest, mode=mode, compresslevel=level) as archive:  # type: tarfile.TarFile
        for path in sorted(source.iterdir()):
            if path.name in ('Cache', 'Logs', 'Diagnostics'):
                log.log(19, f'Skipping: {path}')
            elif path.name == 'Plug-in Support':
                for sub_path in sorted(path.iterdir()):
                    if sub_path.name == 'Caches':
                        log.log(19, f'Skipping: {sub_path}')
                    elif sub_path.name == 'Databases':
                        for db_path in sorted(sub_path.iterdir()):
                            if db_backup_match(db_path.suffix):
                                log.log(19, f'Skipping: {db_path}')
                            else:
                                log.log(19, f'Adding: {db_path}')
                                archive.add(db_path, f'Plex Media Server/Plug-in Support/Databases/{db_path.name}')
                    else:
                        log.log(19, f'Adding: {sub_path}')
                        archive.add(sub_path, f'Plex Media Server/Plug-in Support/{sub_path.name}')
            else:
                log.log(19, f'Adding: {path}')
                archive.add(path, f'Plex Media Server/{path.name}')


def normalize_source(source_str: str) -> Path:
    source = Path(source_str).resolve()
    if not source.is_dir():
        raise ValueError(f'Invalid source directory: {source_str!r}')

    if source.name != 'Plex Media Server':
        pms = next((p for p in source.iterdir() if p.name == 'Plex Media Server'), None)
        if pms:
            source = pms
        else:
            raise ValueError(f'Unexpected directory: {source}')
    return source


def prepare_dest(destination: str, mode: Optional[str]) -> Tuple[Path, str]:
    dest = Path(destination).resolve()
    if dest.is_dir():
        mode = mode or 'gz'
        dt_str = datetime.now().strftime('%Y-%m-%d')
        dest = dest.joinpath(f'plex_backup_{dt_str}.tar.{mode}')
        i = 0
        while dest.exists():
            i += 1
            dest = dest.parent.joinpath(f'plex_backup_{dt_str}_{i}.tar.{mode}')
    elif mode is None:
        m = re.match(r'\.(?:tar\.|t)(gz|bz2|xz)', destination, re.IGNORECASE)
        if m:
            mode = m.group(1)
        else:
            mode = 'gz'

    if not dest.parent.exists():
        dest.parent.mkdir(parents=True)

    return dest, mode


if __name__ == '__main__':
    main()
