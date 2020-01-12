#!/usr/bin/env python3
"""
Manage DBCache cache files

:author: Doug Skrypa
"""

import logging
import sys
from fnmatch import fnmatch
from pathlib import Path
from urllib.parse import quote as url_quote

sys.path.append(Path(__file__).resolve().parents[1].as_posix())
from ds_tools.argparsing import ArgParser
from ds_tools.caching import DBCache
from ds_tools.logging import init_logging
from ds_tools.output import uprint

log = logging.getLogger('ds_tools.{}'.format(__name__))


def parser():
    parser = ArgParser(description='DBCache Manager')

    list_parser = parser.add_subparser('action', 'list', help='List items in the given cache file')
    list_parser.add_argument('path', help='Path to a DBCache file')

    del_parser = parser.add_subparser('action', 'delete', help='Delete items from the given cache file')
    del_parser.add_argument('path', help='Path to a DBCache file')
    del_parser.add_argument('patterns', nargs='+', help='One or more glob/fnmatch patterns to match against keys to be deleted')

    get_parser = parser.add_subparser('action', 'get', help='View information about an entry in the given cache file')
    get_parser.add_argument('path', help='Path to a DBCache file')
    get_parser.add_argument('key', help='Key to retrieve')

    parser.include_common_args('verbosity', 'dry_run')
    return parser


def main():
    args = parser().parse_args()
    init_logging(args.verbose, log_path=None)

    cache = DBCache(None, db_path=args.path)

    if args.action == 'list':
        for key, orig in normalized_keys(cache):
            uprint(key)
    elif args.action == 'delete':
        prefix = '[DRY RUN] Would delete' if args.dry_run else 'Deleting'
        for key, orig in normalized_keys(cache):
            if any(fnmatch(key, pat) for pat in args.patterns):
                log.info('{}: {}'.format(prefix, key))
                if not args.dry_run:
                    del cache[orig]
    elif args.action == 'get':
        entry = cache[args.key]
        log.info(entry)
    else:
        raise ValueError('Unconfigured action: {}'.format(args.action))


def normalized_keys(cache):
    keys = []
    for key in cache.keys():
        orig = key
        if not isinstance(key, str):
            url, qs = key
            key = '{}?{}'.format(url, '&'.join('{}={}'.format(k, url_quote(v)) for k, v in sorted(qs)))
        keys.append((key, orig))
    return sorted(keys)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print()

