#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Manage music files

:author: Doug Skrypa
"""

import argparse
import logging
import os
import sys

import mutagen

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ds_tools.logging import LogManager
from ds_tools.utils import Table, SimpleColumn, validate_or_make_dir
from music.constants import tag_name_map

log = logging.getLogger("ds_tools.{}".format(__file__))


def main():
    parser = argparse.ArgumentParser(description="Music Manager")
    sparsers = parser.add_subparsers(dest="action", help="Action to perform")

    info_parser = sparsers.add_parser("info", help="Get song/tag information")
    info_parser.add_argument("path", nargs="+", help="One or more file/directory paths that contain music files")

    parser.add_argument("--verbose", "-v", action="count", help="Print more verbose log info (may be specified multiple times to increase verbosity)")
    args = parser.parse_args()
    LogManager.create_default_logger(args.verbose, log_path=None)

    i = 0
    if args.action == "info":
        for path in args.path:
            if os.path.isdir(path):
                for root, dirs, files in os.walk(path):
                    for f in files:
                        if i:
                            print()
                        print_song_tags(os.path.join(root, f))
                        i += 1
            elif os.path.isfile(path):
                if i:
                    print()
                print_song_tags(path)
                i += 1
            else:
                log.error("Invalid path: {}".format(path))


def print_song_tags(path):
    f = mutagen.File(path)
    print("{} (ID3v{}.{}):".format(path, *f.tags.version[:2]))
    tbl = Table(SimpleColumn("Tag"),SimpleColumn("Tag Name"), SimpleColumn("Value"), update_width=True)
    rows = []
    for tag, val in sorted(f.tags.items()):
        if len(tag) > 4:
            tag = tag[:4]

        val = str(val)
        rows.append({
            "Tag": tag,
            "Tag Name": tag_name_map.get(tag, "[unknown]"),
            "Value": val if len(val) < 200 else "(too long)"
        })
    tbl.print_rows(rows)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print()
