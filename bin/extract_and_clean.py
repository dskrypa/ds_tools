#!/usr/bin/env python3

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, PROJECT_ROOT.joinpath('bin').as_posix())
import _venv  # This will activate the venv, if it exists and is not already active

import logging
import os
import re
from datetime import datetime
from typing import Pattern

sys.path.append(PROJECT_ROOT.as_posix())
from ds_tools.argparsing import ArgParser
from ds_tools.core.main import wrap_main
from ds_tools.fs.archives import ArchiveFile, UnknownArchiveType
from ds_tools.logging import init_logging
from ds_tools.shell import exec_local

log = logging.getLogger(__name__)


def parser():
    parser = ArgParser(description='Extract and cleanup album zips')
    parser.add_argument('path', help='Directory to process')
    parser.add_argument('--old_mode', '-o', action='store_true', help='Use the old extraction mode')
    parser.include_common_args('verbosity')
    return parser


@wrap_main
def main():
    args = parser().parse_args()
    init_logging(args.verbose, log_path=None)

    src_dir = Path(args.path).expanduser().resolve()
    zip_dir = src_dir.parent.joinpath('extracted_{}'.format(datetime.now().strftime('%Y-%m-%d')))
    if args.old_mode:
        old_extract_albums(src_dir, zip_dir)
    else:
        extract_albums(src_dir, zip_dir)

    cleanup_names(src_dir)


def extract_albums(src_dir: Path, zip_dir: Path):
    for artist in src_dir.iterdir():
        if artist.is_dir():
            dest = zip_dir.joinpath(artist.stem)
            if not dest.exists():
                dest.mkdir(parents=True)

            for f in artist.iterdir():
                if f.is_file():
                    try:
                        ArchiveFile(f).extract_all(dest)
                    except UnknownArchiveType as e:
                        log.warning(f'Skipping {f.as_posix()} due to error: {e}')
                    else:
                        f.rename(dest.joinpath(f.name))
        else:
            try:
                ArchiveFile(artist).extract_all(zip_dir)
            except UnknownArchiveType as e:
                log.warning(f'Skipping {artist.as_posix()} due to error: {e}')
            else:
                artist.rename(zip_dir.joinpath(artist.name))


def old_extract_albums(src_dir: Path, zip_dir: Path):
    for artist in src_dir.iterdir():
        if artist.is_dir():
            dest = zip_dir.joinpath(artist.stem)
            if not dest.exists():
                os.makedirs(dest.as_posix())

            for f in artist.iterdir():
                if f.suffix in ('.7z', '.zip'):
                    log.info('Extracting: {}'.format(f.as_posix()))
                    exec_local('7z', 'x', f.as_posix(), '-o{}'.format(artist.as_posix()), mode='raw', raise_nonzero=True)
                    f.rename(dest.joinpath(f.name))
                elif f.suffix == '.rar':
                    log.info('Extracting: {}'.format(f.as_posix()))
                    exec_local('unrar', 'x', f.as_posix(), artist.as_posix(), mode='raw', raise_nonzero=True)
                    f.rename(dest.joinpath(f.name))
                else:
                    log.info('Skipping non-archive: {}'.format(f.as_posix()))
        else:
            log.info('Skipping non-directory at artist level: {}'.format(artist.as_posix()))


def cleanup_names(src_dir: Path):
    file_url_pat = re.compile(r'^\[.*\.com\](.*)', re.IGNORECASE)
    dir_url_pats = [
        re.compile(r'(.*)\[(?:www)?.*\.com\]$', re.IGNORECASE),
        re.compile(r'^\[.*\.com\](.*)$', re.IGNORECASE)
    ]
    for artist in src_dir.iterdir():
        if artist.is_dir():
            for album in artist.iterdir():
                if album.is_dir():
                    for f in album.iterdir():
                        if f.suffix in ('.url', '.htm', '.html', '.db'):
                            log.info(f'Deleting: {f.as_posix()}')
                            f.unlink()
                        else:
                            rename_path(f, file_url_pat)

                    for dir_url_pat in dir_url_pats:
                        rename_path(album, dir_url_pat)
                else:
                    log.info(f'Skipping non-directory at album level: {album.as_posix()}')
        else:
            log.info(f'Skipping non-directory at artist level: {artist.as_posix()}')


def rename_path(path: Path, pat: Pattern):
    if m := pat.match(path.name):
        try:
            cleaned = path.with_name(m.group(1).strip())
        except ValueError as e:
            log.error(f'Unable to rename {path.as_posix()} - {e}')
        else:
            log.info(f'Renaming {path.as_posix()} -> {cleaned.as_posix()}')
            try:
                path.rename(cleaned)
            except OSError as e:
                log.error(e)


if __name__ == '__main__':
    main()
