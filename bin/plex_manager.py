#!/usr/bin/env python3

import argparse
import logging
import sys
from pathlib import Path

from plexapi.base import OPERATORS

sys.path.append(Path(__file__).expanduser().resolve().parents[1].as_posix())
from ds_tools.argparsing import ArgParser
from ds_tools.core import wrap_main
from ds_tools.logging import LogManager
from ds_tools.music import apply_mutagen_patches
from ds_tools.music.plex import LocalPlexServer
from ds_tools.output import bullet_list

log = logging.getLogger('ds_tools.{}'.format(__name__))

apply_mutagen_patches()


def parser():
    parser = ArgParser(description='Plex rating sync tool\n\nYou will be securely prompted for your password for the first login, after which a session token will be cached')

    sync_parser = parser.add_subparser('action', 'sync', help='Sync Plex information')
    ratings_parser = sync_parser.add_subparser('sync_action', 'ratings', help='Sync song rating information between Plex and files')
    ratings_parser.add_argument('direction', choices=('to_files', 'from_files'), help='Direction to sync information')
    ratings_parser.add_argument('--path_filter', '-f', help='If specified, paths that will be synced must contain the given text (not case sensitive)')

    playlists_parser = sync_parser.add_subparser('sync_action', 'playlists', help='Sync playlists with custom filters')

    obj_types = ('track', 'artist', 'album', 'tracks', 'artists', 'albums')
    ops = ', '.join(sorted(list(OPERATORS) + ['like']))

    find_parser = parser.add_subparser('action', 'find', help='Find Plex information')
    find_parser.add_argument('obj_type', choices=obj_types, help='Object type')
    find_parser.add_argument('title', nargs='*', default=None, help='Object title (optional)')
    find_parser.add_argument('--escape', '-e', default='()', help='Escape the provided regex special characters (default: %(default)r)')
    find_parser.add_argument('query', nargs=argparse.REMAINDER, help='Query in the format --field[__operation] value; valid operations: {}'.format(ops))

    rate_parser = parser.add_subparser('action', 'rate', help='Update ratings in Plex')
    rate_parser.add_argument('obj_type', choices=obj_types, help='Object type')
    rate_parser.add_argument('rating', type=int, help='Rating out of 10')
    rate_parser.add_argument('title', nargs='*', default=None, help='Object title (optional)')
    rate_parser.add_argument('--escape', '-e', default='()', help='Escape the provided regex special characters (default: %(default)r)')
    rate_parser.add_argument('query', nargs=argparse.REMAINDER, help='Query in the format --field[__operation] value; valid operations: {}'.format(ops))

    parser.add_common_sp_arg('--server_path_root', '-r', metavar='PATH', help='The root of the path to use from this computer to generate paths to files from the path used by Plex.  When you click on the "..." for a song in Plex and click "Get Info", there will be a path in the "Files" box - for example, "/media/Music/a_song.mp3".  If you were to access that file from this computer, and the path to that same file is "//my_nas/media/Music/a_song.mp3", then the server_path_root would be "//my_nas/" (only needed when not already cached)')
    parser.add_common_sp_arg('--server_url', '-u', metavar='URL', help='The proto://host:port to use to connect to your local Plex server - for example: "https://10.0.0.100:12000" (only needed when not already cached)')
    parser.add_common_sp_arg('--username', '-n', help='Plex username (only needed when a token is not already cached)')
    parser.add_common_sp_arg('--cache_dir', '-c', metavar='PATH', default='~/.plex', help='Directory in which your token and server_path_root / server_url should be cached (default: %(default)s)')

    parser.include_common_args('verbosity', 'dry_run')
    return parser


@wrap_main
def main():
    args, dynamic = parser().parse_with_dynamic_args('query')
    LogManager.create_default_logger(args.verbose, log_path=None)

    plex = LocalPlexServer(args.server_url, args.username, args.server_path_root, args.cache_dir)

    if args.action == 'sync':
        if args.sync_action == 'ratings':
            if args.direction == 'to_files':
                plex.sync_ratings_to_files(args.path_filter, args.dry_run)
            elif args.direction == 'from_files':
                plex.sync_ratings_from_files(args.path_filter, args.dry_run)
            else:
                log.error('Unconfigured direction')
        elif args.sync_action == 'playlists':
            plex.sync_playlist('K-Pop 3+ Stars', userRating__gte=6, genre__like='[kj]-?pop')
            plex.sync_playlist('K-Pop 4+ Stars', userRating__gte=8, genre__like='[kj]-?pop')
            plex.sync_playlist('K-Pop 5 Stars', userRating__gte=10, genre__like='[kj]-?pop')
            plex.sync_playlist(
                'K-Pop Unrated',
                userRating=0,
                genre__like='[kj]-?pop',
                genre__not_like='christmas',
                title__not_like=r'(?:^|\()(?:intro|outro)(?:$|\s|:|\))|\(inst(?:\.?|rumental)|(?:japanese|jp|karaoke|mandarin|chinese) ver(?:\.|sion)|christmas|santa',
                parentTitle__not_like='christmas|santa',
                duration__gte=60000,
                exclude_rated_dupes=True
            )
        else:
            log.error('Unconfigured sync action')
    elif args.action == 'find':
        obj_type, kwargs = parse_filters(args.obj_type, args.title, dynamic, args.escape)
        objects = plex.find_objects(obj_type, **kwargs)
        if objects:
            print(bullet_list(objects))
        else:
            log.warning('No results.')
    elif args.action == 'rate':
        if args.rating < 0 or args.rating > 10:
            raise ValueError('Ratings must be between 0 and 10')
        obj_type, kwargs = parse_filters(args.obj_type, args.title, dynamic, args.escape)
        objects = plex.find_objects(obj_type, **kwargs)
        if not objects:
            log.warning('No results.')
        else:
            for obj in objects:
                log.info('{}: updating rating to {}'.format(obj, args.rating))
                obj.edit(**{'userRating.value': args.rating})
    else:
        log.error('Unconfigured action')


def parse_filters(obj_type, title, filters, escape):
    obj_type = obj_type[:-1] if obj_type.endswith('s') else obj_type
    title = ' '.join(title) if title else None

    escape_tbl = str.maketrans({c: '\\' + c for c in '()[]{}^$+*.?|\\' if c in escape})
    regexcape = lambda text: text.translate(escape_tbl)

    for key, val in filters.items():
        try:
            op = key.rsplit('__', 1)[1]
        except Exception:
            pass
        else:
            if op in ('regex', 'iregex', 'like', 'not_like'):
                filters[key] = regexcape(val)

    if title:
        filters.setdefault('title__like', title)

    log.debug('obj_type={}, title={!r} => query={}'.format(obj_type, title, filters))
    return obj_type, filters


if __name__ == "__main__":
    main()
