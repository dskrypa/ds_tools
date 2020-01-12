#!/usr/bin/env python3
"""
Fetch Korean lyrics and fix the html to make them easier to print

:author: Doug Skrypa
"""

import logging
import sys
from pathlib import Path

sys.path.append(Path(__file__).resolve().parents[1].as_posix())
from ds_tools.argparsing import ArgParser
from ds_tools.logging import init_logging
from ds_tools.lyric_fetcher import SITE_CLASS_MAPPING, HybridLyricFetcher

log = logging.getLogger('ds_tools.{}'.format(__name__))

DEFAULT_SITE = 'colorcodedlyrics'


def parser():
    site_names = sorted(SITE_CLASS_MAPPING.keys())
    parser = ArgParser(description='Lyric Fetcher')

    list_parser = parser.add_subparser('action', 'list', 'List available sites')

    get_parser = parser.add_subparser('action', 'get', 'Retrieve lyrics from a particular page from a single site')
    get_parser.add_argument('song', nargs='+', help='One or more endpoints that contain lyrics for particular songs')
    get_parser.add_argument('--title', '-t', help='Page title to use (default: extracted from lyric page)')
    get_parser.add_argument('--size', '-z', type=int, default=12, help='Font size to use for output')
    get_parser.add_argument('--ignore_len', '-i', action='store_true', help='Ignore stanza length match')
    get_parser.add_argument('--output', '-o', help='Output directory to store the lyrics')
    get_parser.add_argument('--linebreaks', '-lb', nargs='+', help='Additional linebreaks to use to split stanzas')
    get_parser.add_argument('--replace_lb', '-R', action='store_true', help='Replace existing linebreaks')

    search_parser = parser.add_subparser('action', 'search', 'Search for lyric pages')
    search_parser.add_argument('query', help='Query to run')
    search_parser.add_argument('--sub_query', '-q', help='Sub-query to run')

    index_parser = parser.add_subparser('action', 'index', 'View lyric page endpoints from an artist\'s index page')
    index_parser.add_argument('index', help='Name of the index to view')
    index_parser.add_argument('--album_filter', '-af', help='Filter for albums to be displayed')
    index_parser.add_argument('--list', '-L', action='store_true', help='List albums instead of song links (default: %(default)s)')

    cmp_parser = parser.add_subparser('action', 'compare', 'Compare lyrics from separate songs for common phrases, etc')
    cmp_parser.add_argument('song_1', help='One or more endpoints that contain lyrics for particular songs')
    cmp_parser.add_argument('song_2', help='One or more endpoints that contain lyrics for particular songs')

    for _parser in (get_parser, search_parser, index_parser, cmp_parser):
        _parser.add_argument('--site', '-s', choices=site_names, default=DEFAULT_SITE, help='Site to use (default: %(default)s)')

    hybrid_parser = parser.add_subparser('action', 'hybrid_get', 'Retrieve lyrics from two separate sites and merge them')
    hybrid_parser.add_argument('--korean_site', '-ks', choices=site_names, help='Site from which Korean lyrics should be retrieved', required=True)
    hybrid_parser.add_argument('--english_site', '-es', choices=site_names, help='Site from which the English translation should be retrieved', required=True)
    hybrid_parser.add_argument('--korean_endpoint', '-ke', help='Site from which Korean lyrics should be retrieved', required=True)
    hybrid_parser.add_argument('--english_endpoint', '-ee', help='Site from which the English translation should be retrieved', required=True)

    hybrid_parser.add_argument('--title', '-t', help='Page title to use (default: last part of song endpoint)')
    hybrid_parser.add_argument('--size', '-z', type=int, default=12, help='Font size to use for output')
    hybrid_parser.add_argument('--ignore_len', '-i', action='store_true', help='Ignore stanza length match')
    hybrid_parser.add_argument('--output', '-o', help='Output directory to store the lyrics')

    hybrid_parser.add_argument('--english_lb', '-el', nargs='+', help='Additional linebreaks to use to split English stanzas')
    hybrid_parser.add_argument('--korean_lb', '-kl', nargs='+', help='Additional linebreaks to use to split Korean stanzas')

    hybrid_parser.add_argument('--english_extra', '-ex', nargs='+', help='Additional lines to add to the English stanzas at the end')
    hybrid_parser.add_argument('--korean_extra', '-kx', nargs='+', help='Additional lines to add to the Korean stanzas at the end')

    file_parser = parser.add_subparser('action', 'file_get', 'Retrieve lyrics from two separate text files and merge them')
    file_parser.add_argument('--korean', '-k', metavar='PATH', help='Path to a text file containing Korean lyrics')
    file_parser.add_argument('--english', '-e', metavar='PATH', help='Path to a text file containing the English translation')
    file_parser.add_argument('--title', '-t', help='Page title to use', required=True)
    file_parser.add_argument('--size', '-z', type=int, default=12, help='Font size to use for output')
    file_parser.add_argument('--output', '-o', help='Output directory to store the processed lyrics')

    parser.include_common_args('verbosity')
    return parser


# noinspection PyTypeChecker
def main():
    args = parser().parse_args(req_subparser_value=True)
    init_logging(args.verbose, log_path=None)

    if args.action == 'file_get':
        args.action = 'hybrid_get'
        args.korean_site = 'file'
        args.english_site = 'file'
        args.korean_endpoint = args.korean
        args.english_endpoint = args.english
        args.english_lb = None
        args.korean_lb = None
        args.ignore_len = None
        args.english_extra = None
        args.korean_extra = None

    if args.action == 'list':
        for site in sorted(SITE_CLASS_MAPPING.keys()):
            print(site)
    elif args.action in ('get', 'search', 'index', 'compare'):
        try:
            lf = SITE_CLASS_MAPPING[args.site]()
        except KeyError as e:
            raise ValueError('Unconfigured site: {}'.format(args.site)) from e

        if args.action == 'search':
            lf.print_search_results(args.query, args.sub_query)
        elif args.action == 'index':
            lf.print_index_results(args.index, args.album_filter, args.list)
        elif args.action == 'get':
            linebreaks = {int(str(val).strip()) for val in args.linebreaks or []}
            extra_linebreaks = {'English': linebreaks, 'Korean': linebreaks}
            for song in args.song:
                lf.process_lyrics(
                    song, args.title, args.size, args.ignore_len, args.output,
                    extra_linebreaks=extra_linebreaks, replace_lb=args.replace_lb
                )
        elif args.action == 'compare':
            lf.compare_lyrics(args.song_1, args.song_2)
        else:
            raise ValueError('Unconfigured action: {}'.format(args.action))
    elif args.action == 'hybrid_get':
        fetchers = {}
        for lang in ('korean', 'english'):
            site = getattr(args, lang + '_site')
            try:
                fetchers[lang] = SITE_CLASS_MAPPING[site]()
            except KeyError as e:
                raise ValueError('Unconfigured site for {} lyrics: {}'.format(lang.title(), site)) from e

        hlf = HybridLyricFetcher(fetchers['korean'], fetchers['english'])

        extra_linebreaks = {
            'English': {int(str(val).strip()) for val in args.english_lb or []},
            'Korean': {int(str(val).strip()) for val in args.korean_lb or []}
        }
        extra_lines = {'English': args.english_extra or [], 'Korean': args.korean_extra or []}
        hlf.process_lyrics(
            None, args.title, args.size, args.ignore_len, args.output,
            kor_endpoint=args.korean_endpoint, eng_endpoint=args.english_endpoint,
            extra_linebreaks=extra_linebreaks, extra_lines=extra_lines
        )
    else:
        raise ValueError('Unconfigured action: {}'.format(args.action))


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print()

