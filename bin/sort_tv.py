#!/usr/bin/env python3

import logging
import re
import sys
from pathlib import Path

sys.path.append(Path(__file__).expanduser().resolve().parents[1].as_posix())
from ds_tools.argparsing import ArgParser
from ds_tools.logging import LogManager
from ds_tools.shell import exec_local, ExternalProcessException

log = logging.getLogger('ds_tools.{}'.format(__name__))


def parser():
    parser = ArgParser(description='Sort TV show parts')
    parser.add_argument('path', help='Directory to process')
    parser.include_common_args('verbosity')
    return parser


def main():
    args = parser().parse_args()
    LogManager.create_default_logger(args.verbose, log_path=None)

    src_dir = Path(args.path).expanduser().resolve()
    ep_pat = re.compile(r'^(.+)[^a-zA-Z0-9]S(\d+)E(\d+)\D.*', re.IGNORECASE)

    for p in src_dir.iterdir():
        if p.is_file():
            m = ep_pat.match(p.name)
            if m:
                show, season, episode = m.groups()
                season= int(season)
                episode = int(episode)
                show_dir = src_dir.joinpath(show)
                ep_dir = show_dir.joinpath('S{:02d}E{:02d}'.format(season, episode))
                if not ep_dir.exists():
                    ep_dir.mkdir(parents=True)

                new_path = ep_dir.joinpath(p.name)
                log.info('Moving {} -> {}'.format(p, new_path))
                p.rename(new_path)

    for show_dir in src_dir.iterdir():
        if show_dir.is_dir():
            for ep_path in show_dir.iterdir():
                if ep_path.is_dir():
                    original_contents = set(ep_path.iterdir())
                    process_episode(ep_path)
                    new_contents = set(p for p in ep_path.iterdir() if p.is_file()).difference(original_contents)
                    for p in new_contents:
                        m = ep_pat.match(p.name)
                        if m:
                            show, season, episode = m.groups()
                            season = int(season)
                            season_dir = show_dir.joinpath('Season {}'.format(season))
                            new_path = season_dir.joinpath(p.name)
                            log.info('Moving {} -> {}'.format(p, new_path))
                            p.rename(new_path)


def process_episode(ep_path):
    junk_dir = ep_path.joinpath('junk')
    if not junk_dir.exists():
        junk_dir.mkdir(parents=True)

    parts = [p.as_posix() for p in ep_path.iterdir()]
    par2 = None
    for f in ep_path.iterdir():
        try:
            if f.is_file() and f.suffix.lower() == '.par2' and not f.suffixes[-2].lower().startswith('.vol'):
                par2 = f.as_posix()
                break
        except Exception:
            pass

    if par2:
        try:
            exec_local('par2', 'r', '-v', par2, *parts, mode='raw')
        except ExternalProcessException as e:
            pass
        else:
            par2s = [p for p in parts if p.lower().endswith('.par2')]
            if par2s:
                for p2f in par2s:
                    p2p = Path(p2f)
                    new_p2p = junk_dir.joinpath(p2p.name)
                    log.info('Moving {} -> {}'.format(p2p, new_p2p))
                    p2p.rename(new_p2p)

    for f in [p for p in ep_path.iterdir() if p.suffix.lower() in ('.7z', '.zip', '.rar')]:
        existing = set(ep_path.iterdir())
        log.info('Extracting: {}'.format(f.as_posix()))
        try:
            if f.suffix in ('.7z', '.zip'):
                exec_local('7z', 'x', f.as_posix(), '-o{}'.format(ep_path.as_posix()), mode='raw')
            elif f.suffix == '.rar':
                exec_local('unrar', 'x', f.as_posix(), ep_path.as_posix(), mode='raw')
        except ExternalProcessException as e:
            pass
        else:
            for p in existing:
                if p.stem == f.stem:
                    new_p = junk_dir.joinpath(p.name)
                    log.info('Moving {} -> {}'.format(p, new_p))
                    p.rename(new_p)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print()
