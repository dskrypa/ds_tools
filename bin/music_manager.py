#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Manage music files

:author: Doug Skrypa
"""

import argparse
import logging
import os
import string
import sys
from collections import Counter, defaultdict

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

    stat_group = info_parser.add_mutually_exclusive_group()
    stat_group.add_argument("--count", "-c", action="store_true", help="Count tag types rather than printing all info")
    stat_group.add_argument("--unique", "-u", metavar="TAGID", nargs="+", help="Count unique values of the specified tag(s)")

    parser.add_argument("--verbose", "-v", action="count", help="Print more verbose log info (may be specified multiple times to increase verbosity)")
    args = parser.parse_args()
    LogManager.create_default_logger(args.verbose, log_path=None)

    if args.action == "info":
        if args.count:
            count_tag_types(args.path)
        elif args.unique:
            count_unique_vals(args.path, args.unique)
        else:
            print_song_tags(args.path)


def iter_music_files(paths):
    for path in paths:
        if os.path.isdir(path):
            for root, dirs, files in os.walk(path):
                for f in files:
                    file_path = os.path.join(root, f)
                    music_file = mutagen.File(file_path)
                    if music_file:
                        yield music_file
                    else:
                        log.debug("Not a music file: {}".format(file_path))
        elif os.path.isfile(path):
            music_file = mutagen.File(path)
            if music_file:
                yield music_file
            else:
                log.debug("Not a music file: {}".format(path))
        else:
            log.error("Invalid path: {}".format(path))


def print_song_tags(paths):
    i = 0
    for music_file in iter_music_files(paths):
        if i:
            print()
        print("{} (ID3v{}.{}):".format(music_file.filename, *music_file.tags.version[:2]))
        tbl = Table(SimpleColumn("Tag"), SimpleColumn("Tag Name"), SimpleColumn("Value"), update_width=True)
        rows = []
        for tag, val in sorted(music_file.tags.items()):
            if len(tag) > 4:
                tag = tag[:4]

            val = str(val)
            rows.append({
                "Tag": tag,
                "Tag Name": tag_name_map.get(tag, "[unknown]"),
                "Value": val if len(val) < 200 else "(too long)"
            })
        tbl.print_rows(rows)
        i += 1


def count_unique_vals(paths, tag_ids):
    include = {tag_id.upper() for tag_id in tag_ids}
    if not include:
        raise ValueError("Unable to count unique values of tags if no tag IDs were provided")

    unique_vals = defaultdict(Counter)
    for music_file in iter_music_files(paths):
        for tag, val in music_file.tags.items():
            tag = tag[:4]
            if tag in include:
                unique_vals[tag][str(val)] += 1

    tbl = Table(
        SimpleColumn("Tag"), SimpleColumn("Tag Name"), SimpleColumn("Count", align=">", ftype=",d"),
        SimpleColumn("Value"), update_width=True
    )
    rows = []

    # Translate whitespace characters (such as \n, \r, etc.) to their escape sequences
    esc_trans = str.maketrans({c: c.encode("unicode_escape").decode("utf-8") for c in string.whitespace})

    for tag, val_counter in unique_vals.items():
        for val, count in val_counter.items():
            val = val.translate(esc_trans)
            if len(val) > 150:
                val = "{}...{}".format(val[:25], val[-25:])
            rows.append({"Tag": tag, "Tag Name": tag_name_map.get(tag, "[unknown]"), "Count": count, "Value": val})
    tbl.print_rows(rows)


def count_tag_types(paths):
    total_tags = Counter()
    unique_tags = Counter()
    unique_values = defaultdict(Counter)
    id3_versions = Counter()
    files = 0
    for music_file in iter_music_files(paths):
        files += 1
        tag_set = set()
        for tag, val in music_file.tags.items():
            tag = tag[:4]
            tag_set.add(tag)
            total_tags[tag] += 1
            unique_values[tag][str(val)] += 1

        unique_tags.update(tag_set)
        id3_versions.update(["ID3v{}.{}".format(*music_file.tags.version[:2])])

    tag_rows = []
    for tag in unique_tags:
        tag_rows.append({
            "Tag": tag, "Tag Name": tag_name_map.get(tag, "[unknown]"), "Total": total_tags[tag],
            "Files": unique_tags[tag], "Files %": unique_tags[tag]/files,
            "Per File (overall)": total_tags[tag]/files, "Per File (with tag)": total_tags[tag]/unique_tags[tag],
            "Unique Values": len(unique_values[tag])
        })

    tbl = Table(
        SimpleColumn("Tag"), SimpleColumn("Tag Name"), SimpleColumn("Total", align=">", ftype=",d"),
        SimpleColumn("Files", align=">", ftype=",d"), SimpleColumn("Files %", align=">", ftype=",.0%"),
        SimpleColumn("Per File (overall)", align=">", ftype=",.2f"),
        SimpleColumn("Per File (with tag)", align=">", ftype=",.2f"),
        SimpleColumn("Unique Values", align=">", ftype=",d"),
        update_width=True, sort_by="Tag"
    )
    tbl.print_rows(tag_rows)

    print()
    tbl = Table(SimpleColumn("Version"), SimpleColumn("Count"), update_width=True, sort_by="Version")
    tbl.print_rows([{"Version": ver, "Count": count} for ver, count in id3_versions.items()])


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print()
