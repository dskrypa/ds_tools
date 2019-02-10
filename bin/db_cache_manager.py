#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Manage DBCache cache files

:author: Doug Skrypa
"""

import logging
import sys
from fnmatch import fnmatch
from pathlib import Path

sys.path.append(Path(__file__).expanduser().resolve().parents[1].as_posix())
from ds_tools.logging import LogManager
from ds_tools.utils import ArgParser, DBCache, uprint

log = logging.getLogger("ds_tools.{}".format(__name__))


def parser():
    parser = ArgParser(description="DBCache Manager")

    list_parser = parser.add_subparser("action", "list", help="List items in the given cache file")
    list_parser.add_argument("path", help="Path to a DBCache file")

    del_parser = parser.add_subparser("action", "delete", help="Delete items from the given cache file")
    del_parser.add_argument("path", help="Path to a DBCache file")
    del_parser.add_argument("patterns", nargs="+", help="One or more glob/fnmatch patterns to match against keys to be deleted")

    parser.include_common_args("verbosity", "dry_run")
    return parser


def main():
    args = parser().parse_args()
    LogManager.create_default_logger(args.verbose, log_path=None)

    cache = DBCache(None, db_path=args.path)

    if args.action == "list":
        for key in sorted(cache.keys()):
            uprint(key)
    elif args.action == "delete":
        prefix = "[DRY RUN] Would delete" if args.dry_run else "Deleting"
        for key in sorted(cache.keys()):
            if any(fnmatch(key, pat) for pat in args.patterns):
                log.info("{}: {}".format(prefix, key))
                if not args.dry_run:
                    del cache[key]


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print()

