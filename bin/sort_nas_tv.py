#!/usr/bin/env python3

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, PROJECT_ROOT.joinpath('bin').as_posix())
import _venv  # This will activate the venv, if it exists and is not already active

import logging
import re
from collections import Counter
from typing import Dict

sys.path.append(PROJECT_ROOT.as_posix())
from ds_tools.__version__ import __author_email__, __version__
from ds_tools.argparsing import ArgParser
from ds_tools.core.main import wrap_main
from ds_tools.fs.copy import copy_file
from ds_tools.logging import init_logging

log = logging.getLogger(__name__)


def parser():
    parser = ArgParser(description='Sort TV show episodes')
    parser.add_argument('src_path', help='Source directory')
    parser.add_argument('dst_path', help='Target directory')
    parser.add_argument('--rm', '-r', action='store_true', help='Remove files after copying')
    parser.add_argument('--no-refresh', '-F', dest='refresh', action='store_false', help='Do not check for newly added files in src_path after copying existing files')
    parser.add_argument('--show-dests', '-S', action='store_true', help='Show show destination paths instead of copying any files')
    parser.add_argument('--buf_size', '-b', type=int, help='Copy buffer size (default: usually ~8MB)')
    parser.include_common_args('verbosity', 'dry_run')
    return parser


@wrap_main
def main():
    args = parser().parse_args()
    init_logging(args.verbose, log_path=None)

    src_dir = Path(args.src_path).expanduser().resolve()
    dst_dir = Path(args.dst_path).expanduser().resolve()
    dst_shows = get_destinations(dst_dir)

    if args.show_dests:
        from ds_tools.output.table import Table
        rows = [{'Show': dst_show, 'Path': dst_path.as_posix()} for dst_show, dst_path in dst_shows.items()]
        Table.auto_print_rows(rows, sort_by='Show', sort_keys=False)
    else:
        src_moved_dir = src_dir.parent.joinpath(f'{src_dir.name}_moved')
        if not args.rm and not args.dry_run and not src_moved_dir.exists():
            src_moved_dir.mkdir(parents=True)

        refresh = args.refresh and not args.dry_run
        copy_args = (src_dir, src_moved_dir, dst_shows, args.dry_run, args.rm, args.buf_size)
        while (copied := copy_shows(*copy_args)) and refresh:
            log.debug(f'Copied {copied} files.  Checking for newly added files...')


def get_destinations(dst_dir: Path) -> Dict[str, Path]:
    dst_shows = {norm_show(sp.name): sp for sp in dst_dir.iterdir() if sp.is_dir()}
    aliases = {
        'penn and teller fool us': 'fool us',
        'last week tonight with john oliver': 'last week tonight',
        'the stand 2020': 'the stand',
    }
    for alias, target in aliases.items():
        if dst_path := dst_shows.get(target):
            dst_shows[alias] = dst_path
    return dst_shows


def copy_shows(src_dir: Path, src_moved_dir: Path, dst_shows: Dict[str, Path], dry_run: bool, rm: bool, buf_size: int):
    cp_prefix = '[DRY RUN] Would copy' if dry_run else 'Copying'
    mv_prefix = '[DRY RUN] Would move' if dry_run else 'Moving'
    rm_prefix = '[DRY RUN] Would delete' if dry_run else 'Deleting'
    title_match = re.compile(r'^(.+)\.S(\d\d)E(\d\d)\..*', re.IGNORECASE).match
    copied = 0
    for copied, ep_path in enumerate(src_dir.iterdir(), 1):
        if m := title_match(ep_path.stem):
            show, season, ep_num = m.groups()
            normalized = norm_show(show.replace('.', ' '))
            if dst_show_dir := dst_shows.get(normalized):
                dst_season_dir = get_season_dir(dst_show_dir, int(season))
                dst_ep_path = dst_season_dir.joinpath(ep_path.name)
                if dst_ep_path.exists():
                    log.info(f'Already exists: {dst_ep_path}')
                    continue
                
                log.info(f'{cp_prefix} {ep_path.name} -> {dst_ep_path}')
                if not dry_run:
                    if not dst_season_dir.exists():
                        dst_season_dir.mkdir(parents=True)

                    copy_file(ep_path, dst_ep_path, buf_size=buf_size)
                    if rm:
                        log.info(f'{rm_prefix} {ep_path}')
                        ep_path.unlink()
                    else:
                        moved_path = src_moved_dir.joinpath(ep_path.name)
                        log.info(f'{mv_prefix} {ep_path.name} -> {moved_path}')
                        ep_path.rename(moved_path)
            else:
                log.warning(f'No destination found for {show!r} / {normalized!r}')

    return copied


def get_season_dir(dst_show_dir: Path, season: int) -> Path:
    season_prefixes = Counter()
    for season_dir in dst_show_dir.iterdir():
        if season_dir.is_dir():
            try:
                prefix, num = season_dir.stem.split()
                dir_num = int(num)
            except Exception:
                pass
            else:
                season_prefixes[prefix] += 1
                if dir_num == season:
                    return season_dir
    else:
        try:
            prefix = max(season_prefixes, key=lambda k: season_prefixes[k])
        except ValueError:
            prefix = 'Season'

        return dst_show_dir.joinpath(f'{prefix} {season}')


def norm_show(show):
    try:
        alnum_sub = norm_show._alnum_sub
    except AttributeError:
        alnum_sub = norm_show._alnum_sub = re.compile(r'[^0-9a-zA-Z ]').sub
    return alnum_sub('', show).lower()


if __name__ == '__main__':
    main()
