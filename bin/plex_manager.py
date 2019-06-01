#!/usr/bin/env python3

import logging
import sys
from pathlib import Path

sys.path.append(Path(__file__).expanduser().resolve().parents[1].as_posix())
from ds_tools.argparsing import ArgParser
from ds_tools.logging import LogManager
from ds_tools.music import apply_mutagen_patches
from ds_tools.music.plex import LocalPlexServer

log = logging.getLogger('ds_tools.{}'.format(__name__))

apply_mutagen_patches()


def parser():
    parser = ArgParser(description='Plex rating sync tool\n\nYou will be securely prompted for your password for the first login, after which a session token will be cached')

    sync_parser = parser.add_subparser('action', 'sync', help='Sync Plex information')
    ratings_parser = sync_parser.add_subparser('sync_action', 'ratings', help='Sync song rating information between Plex and files')
    ratings_parser.add_argument('direction', choices=('to_files', 'from_files'), help='Direction to sync information')
    ratings_parser.add_argument('--path_filter', '-f', help='If specified, paths that will be synced must contain the given text (not case sensitive)')

    playlists_parser = sync_parser.add_subparser('sync_action', 'playlists', help='Sync playlists with custom filters')

    parser.add_common_sp_arg('--server_path_root', '-r', metavar='PATH', help='The root of the path to use from this computer to generate paths to files from the path used by Plex.  When you click on the "..." for a song in Plex and click "Get Info", there will be a path in the "Files" box - for example, "/media/Music/a_song.mp3".  If you were to access that file from this computer, and the path to that same file is "//my_nas/media/Music/a_song.mp3", then the server_path_root would be "//my_nas/" (only needed when not already cached)')
    parser.add_common_sp_arg('--server_url', '-u', metavar='URL', help='The proto://host:port to use to connect to your local Plex server - for example: "https://10.0.0.100:12000" (only needed when not already cached)')
    parser.add_common_sp_arg('--username', '-n', help='Plex username (only needed when a token is not already cached)')
    parser.add_common_sp_arg('--cache_dir', '-c', metavar='PATH', default='~/.plex', help='Directory in which your token and server_path_root / server_url should be cached (default: %(default)s)')

    parser.include_common_args('verbosity', 'dry_run')
    return parser


def main():
    args = parser().parse_args()
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
        else:
            log.error('Unconfigured sync action')
    else:
        log.error('Unconfigured action')


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print()
