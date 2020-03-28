#!/usr/bin/env python

import logging
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.append(Path(__file__).resolve().parents[1].as_posix())
from ds_tools.argparsing import ArgParser
from ds_tools.fs import copy_file
from ds_tools.logging import init_logging

log = logging.getLogger('ds_tools.{}'.format(__name__))

ALNUM_PAT = re.compile(r'[^0-9a-zA-Z ]')


def parser():
    parser = ArgParser(description='Sort TV show episodes')
    parser.add_argument('src_path', help='Source directory')
    parser.add_argument('dst_path', help='Target directory')
    parser.add_argument('--rm', '-r', action='store_true', help='Remove files after copying')
    parser.include_common_args('verbosity', 'dry_run')
    return parser


def norm_show(show):
    return ALNUM_PAT.sub('', show).lower()


def main():
    args = parser().parse_args()
    init_logging(args.verbose, log_path=None)

    src_dir = Path(args.src_path).expanduser().resolve()
    src_moved_dir = src_dir.parent.joinpath('{}_moved'.format(src_dir.name))
    dst_dir = Path(args.dst_path).expanduser().resolve()
    if not args.rm and not args.dry_run and not src_moved_dir.exists():
        src_moved_dir.mkdir(parents=True)

    title_pat = re.compile(r'^(.+)\.S(\d\d)E(\d\d)\..*', re.IGNORECASE)
    dst_shows = {norm_show(sp.name): sp for sp in dst_dir.iterdir() if sp.is_dir()}
    if 'fool us' in dst_shows:
        dst_shows['penn and teller fool us'] = dst_shows['fool us']
#    for dst_show, dst_p in dst_shows.items():
#        if 'mr' in dst_show:
#            print('{!r} => {}'.format(dst_show, dst_p))
    
    cp_prefix = '[DRY RUN] Would copy' if args.dry_run else 'Copying'
    mv_prefix = '[DRY RUN] Would move' if args.dry_run else 'Moving'
    rm_prefix = '[DRY RUN] Would delete' if args.dry_run else 'Deleting'

    for ep_path in src_dir.iterdir():
        m = title_pat.match(ep_path.stem)
        if m:
            show, season, ep_num = m.groups()
            normalized = norm_show(show.replace('.', ' '))
            dst_show_dir = dst_shows.get(normalized)
            if dst_show_dir:
                dst_season_dir = None
                season_prefixes = Counter()
                season = int(season)
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
                                dst_season_dir = season_dir
                                break
                else:
                    try:
                        prefix = max(season_prefixes, key=lambda k: season_prefixes[k])
                    except ValueError:
                        prefix = 'Season'

                    dst_season_dir = dst_show_dir.joinpath('{} {}'.format(prefix, season))

                dst_ep_path = dst_season_dir.joinpath(ep_path.name)
                if dst_ep_path.exists():
                    log.info('Already exists: {}'.format(dst_ep_path))
                    continue
                
                log.info('{} {} -> {}'.format(cp_prefix, ep_path.name, dst_ep_path))
                if not args.dry_run:
                    if not dst_season_dir.exists():
                        dst_season_dir.mkdir(parents=True)
                    copy_file(ep_path, dst_ep_path)
                    if args.rm:
                        log.info('{} {}'.format(rm_prefix, ep_path))
                        ep_path.unlink()
                    else:
                        moved_path = src_moved_dir.joinpath(ep_path.name)
                        log.info('{} {} -> {}'.format(mv_prefix, ep_path.name, moved_path))
                        ep_path.rename(moved_path)
            else:
                log.warning('No destination found for {!r} / {!r}'.format(show, normalized))


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print()
