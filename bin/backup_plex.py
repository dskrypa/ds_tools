#!/usr/bin/env python

import logging
import re
import tarfile
from argparse import ArgumentParser
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple
from subprocess import Popen, PIPE

try:
    import tqdm
except ImportError:
    tqdm = None

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

    skip_dirs = {'Cache', 'Logs', 'Diagnostics'}

    try:
        # prog_bar = tqdm.tqdm(desc='', total=count_files(source, db_backup_match, skip_dirs), unit='file')
        prog_bar = tqdm.tqdm(desc='', total=get_size(source, db_backup_match, skip_dirs), unit='bytes')
        update_progress = prog_bar.update
    except AttributeError:
        update_progress = lambda: None  # noqa

    from builtins import open as bltn_open

    with tarfile.open(dest, mode=mode, compresslevel=level) as archive:  # type: tarfile.TarFile
        add_file = archive.addfile
        make_tar_info = archive.gettarinfo

        def add_path(src_path: Path, arc_path: str):
            tarinfo = make_tar_info(src_path, arc_path)  # noqa
            if tarinfo.isreg():
                with bltn_open(src_path, 'rb') as f:
                    add_file(tarinfo, f)
            elif tarinfo.isdir():
                add_file(tarinfo)
                for p in sorted(src_path.iterdir()):
                    add_path(p, f'{arc_path}/{p.name}')
            else:
                add_file(tarinfo)

            update_progress(tarinfo.size)

        for path in sorted(source.iterdir()):
            if path.name in skip_dirs:
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
                                add_path(db_path, f'Plex Media Server/Plug-in Support/Databases/{db_path.name}')
                                # archive.add(db_path, f'Plex Media Server/Plug-in Support/Databases/{db_path.name}')
                                # update_progress()
                    else:
                        log.log(19, f'Adding: {sub_path}')
                        add_path(sub_path, f'Plex Media Server/Plug-in Support/{sub_path.name}')
                        # archive.add(sub_path, f'Plex Media Server/Plug-in Support/{sub_path.name}')
                        # update_progress()
            else:
                log.log(19, f'Adding: {path}')
                add_path(path, f'Plex Media Server/{path.name}')
                # archive.add(path, f'Plex Media Server/{path.name}')
                # update_progress()

    try:
        prog_bar.close()  # noqa
    except (AttributeError, NameError):
        pass


def get_size(source: Path, db_backup_match, skip_dirs) -> int:
    size = 0
    for path in source.iterdir():
        if path.name == 'Plug-in Support':
            for sub_path in path.iterdir():
                if sub_path.name == 'Databases':
                    for db_path in sub_path.iterdir():
                        if not db_backup_match(db_path.suffix):
                            size += _get_size(db_path)
                elif sub_path.name != 'Caches':
                    size += _get_size(sub_path)
        elif path.name not in skip_dirs:
            size += _get_size(path)

    return size


def _get_size(path: Path) -> int:
    if path.is_file():
        return path.lstat().st_size

    proc = Popen(['du', '-s', path.as_posix()], stdout=PIPE)
    proc.wait()
    stdout, stderr = proc.communicate()
    return int(stdout.split()[0])


def count_files(source: Path, db_backup_match, skip_dirs) -> int:
    n = 0
    for path in source.iterdir():
        if path.name == 'Plug-in Support':
            for sub_path in path.iterdir():
                if sub_path.name == 'Databases':
                    for db_path in sub_path.iterdir():
                        if not db_backup_match(db_path.suffix):
                            n += _count_files(db_path)
                elif sub_path.name != 'Caches':
                    n += _count_files(sub_path)
        elif path.name not in skip_dirs:
            n += _count_files(path)

    return n


def _count_files(path: Path) -> int:
    if path.is_file():
        return 1

    find_proc = Popen(['find', path.as_posix()], stdout=PIPE)
    wc_proc = Popen(['wc', '-l'], stdin=find_proc.stdout, stdout=PIPE)
    wc_proc.wait()
    stdout, stderr = wc_proc.communicate()
    return int(stdout.strip())


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
