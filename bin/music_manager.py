#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Manage music files

:author: Doug Skrypa
"""

import argparse
import logging
import os
import pickle
import string
import sys
from collections import Counter, defaultdict
from fnmatch import fnmatch
from hashlib import sha256
from io import BytesIO
from itertools import chain

import grapheme
import mutagen
from mutagen.id3._frames import Frame

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ds_tools.logging import LogManager
from ds_tools.utils import Table, SimpleColumn, validate_or_make_dir
from music.constants import tag_name_map

log = logging.getLogger("ds_tools.{}".format(__name__))

# Translate whitespace characters (such as \n, \r, etc.) to their escape sequences
WHITESPACE_TRANS_TBL = str.maketrans({c: c.encode("unicode_escape").decode("utf-8") for c in string.whitespace})

# Monkey-patch Frame's repr so APIC and similar frames don't kill terminals
_orig_frame_repr = Frame.__repr__
def _frame_repr(self):
    kw = []
    for attr in self._framespec:
        # so repr works during __init__
        if hasattr(self, attr.name):
            kw.append("{}={}".format(attr.name, tag_repr(repr(getattr(self, attr.name)))))
    for attr in self._optionalspec:
        if hasattr(self, attr.name):
            kw.append("{}={}".format(attr.name, tag_repr(repr(getattr(self, attr.name)))))
    return "{}({})".format(type(self).__name__, ", ".join(kw))
Frame.__repr__ = _frame_repr


class FakeMusicFile:
    def __init__(self, sha256sum, tags):
        self.filename = sha256sum
        self.tags = tags


def main():
    parser = argparse.ArgumentParser(description="Music Manager")
    sparsers = parser.add_subparsers(dest="action", help="Action to perform")

    info_parser = sparsers.add_parser("info", help="Get song/tag information")
    info_parser.add_argument("path", nargs="+", help="One or more file/directory paths that contain music files")

    info_group = info_parser.add_mutually_exclusive_group()
    info_group.add_argument("--count", "-c", action="store_true", help="Count tag types rather than printing all info")
    info_group.add_argument("--unique", "-u", metavar="TAGID", nargs="+", help="Count unique values of the specified tag(s)")
    info_group.add_argument("--tags", "-t", nargs="+", help="Filter tags to display in file info mode")

    rm_parser = sparsers.add_parser("remove", help="Remove specified tags from the given files")
    rm_parser.add_argument("path", nargs="+", help="One or more file/directory paths that contain music files")
    rm_parser.add_argument("--tags", "-t", nargs="+", help="One or more tag IDs to remove from the given files")

    cp_parser = sparsers.add_parser("copy", help="Copy specified tags from one set of files to another")
    cp_parser.add_argument("--source", "-s", nargs="+", help="One or more file/directory paths that contain music files or ID3 info backups", required=True)
    cp_parser.add_argument("--dest", "-d", nargs="+", help="One or more file/directory paths that contain music files, or a path to store an ID3 info backup")
    cp_parser.add_argument("--backup", "-b", action="store_true", help="Store a backup of ID3 information instead of writing directly to matching music files")
    cp_parser.add_argument("--tags", "-t", nargs="+", help="One or more tag IDs to copy to the destination files")

    for p in chain((parser,), sparsers.choices.values()):
        p.add_argument("--verbose", "-v", action="count", help="Print more verbose log info (may be specified multiple times to increase verbosity)")
        p.add_argument("--dry_run", "-D", action="store_true", help="Print the actions that would be taken instead of taking them")

    args = parser.parse_args()
    LogManager.create_default_logger(args.verbose, log_path=None)

    if args.action == "info":
        if args.count:
            count_tag_types(args.path)
        elif args.unique:
            count_unique_vals(args.path, args.unique)
        else:
            print_song_tags(args.path, args.tags)
    elif args.action == "remove":
        remove_tags(args.path, args.tags, args.dry_run)
    elif args.action == "copy":
        if args.backup:
            if len(args.dest) > 1:
                raise ValueError("Only one --dest/-d path may be provided in backup mode")
            save_tag_backups(args.source, args.dest)
        else:
            copy_tags(args.source, args.dest, args.tags, args.dry_run)
    else:
        log.error("Unconfigured action")


def copy_tags(source_paths, dest_paths, tags, dry_run):
    if not tags:
        raise ValueError("One or more tags or 'ALL' must be specified for --tags/-t")
    tags = sorted({tag.upper() for tag in tags})
    all_tags = "ALL" in tags
    src_tags = load_tags(source_paths)

    prefix, verb = ("[DRY RUN] ", "Would update") if dry_run else ("", "Updating")

    for music_file in iter_music_files(dest_paths):

        path = music_file.filename
        content_hash = tagless_sha256sum(music_file)
        if content_hash in src_tags:
            if all_tags:
                log.info("{}{} all tags in {}".format(prefix, verb, path))
                if not dry_run:
                    log.info("Saving changes to {}".format(path))
                    src_tags[content_hash].save(path)
            else:
                do_save = False
                for tag in tags:
                    tag_name = tag_name_map.get(tag, "[unknown]")
                    tag_str = "{} ({})".format(tag, tag_name)
                    src_vals = src_tags[content_hash].getall(tag)
                    if not src_vals:
                        log.info("{}: No value found in source for {}".format(path, tag_str))
                    else:
                        dest_vals = music_file.tags.getall(tag)
                        if src_vals == dest_vals:
                            log.info("{}: Source and dest values match for {}".format(path, tag_str))
                        else:
                            dest_val_str = ", ".join(map(tag_repr, dest_vals))
                            src_val_str = ", ".join(map(tag_repr, src_vals))
                            log.info("{}{} {} in {} from [{}] to [{}]".format(prefix, verb, tag_str, path, dest_val_str, src_val_str))
                            if not dry_run:
                                music_file.tags.setall(tag, src_vals)
                                do_save = True
                if do_save:
                    log.info("Saving changes to {}".format(path))
                    music_file.tags.save(path)
        else:
            log.info("{}: sha256sum not found in source paths".format(music_file.filename))


def save_tag_backups(source_paths, backup_path):
    if isinstance(backup_path, (list, tuple)):
        backup_path = backup_path[0]
    if not backup_path:
        backup_path = "/var/tmp/id3_tags.pickled"
    log.info("backup_path: {}".format(backup_path))

    backup_path = os.path.expanduser(backup_path)
    if os.path.exists(backup_path) and os.path.isdir(backup_path):
        backup_path = os.path.join(backup_path, "id3_tags.pickled")

    if os.path.isfile(backup_path):
        tag_info = load_tags([backup_path])
    else:
        tag_info = {}

    for i, music_file in enumerate(iter_music_files(source_paths, include_backups=True)):
        if isinstance(music_file, FakeMusicFile):
            content_hash = music_file.filename
        else:
            content_hash = tagless_sha256sum(music_file)
        log.debug("{}: {}".format(music_file.filename, content_hash))
        tag_info[content_hash] = music_file.tags

    with open(backup_path, "wb") as f:
        log.info("Writing tag info to: {}".format(backup_path))
        pickle.dump(tag_info, f)


def load_tags(paths):
    if isinstance(paths, str):
        paths = [paths]

    tag_info = {}
    for path in paths:
        if os.path.isdir(path):
            for root, dirs, files in os.walk(path):
                for f in files:
                    file_path = os.path.join(root, f)
                    try:
                        music_file = mutagen.File(file_path)
                    except Exception as e:
                        log.debug("Error loading {}: {}".format(file_path, e))
                        music_file = None

                    if music_file:
                        content_hash = tagless_sha256sum(music_file)
                        log.debug("{}: {}".format(music_file.filename, content_hash))
                        tag_info[content_hash] = music_file.tags
                    else:
                        with open(file_path, "rb") as f:
                            try:
                                tag_info.update(pickle.load(f))
                            except Exception as e:
                                log.debug("Unable to load tag info from file: {}".format(file_path))
                            else:
                                log.debug("Loaded pickled tag info from {}".format(file_path))
        elif os.path.isfile(path):
            try:
                music_file = mutagen.File(path)
            except Exception as e:
                log.debug("Error loading {}: {}".format(path, e))
                music_file = None

            if music_file:
                content_hash = tagless_sha256sum(music_file)
                log.debug("{}: {}".format(music_file.filename, content_hash))
                tag_info[content_hash] = music_file.tags
            else:
                with open(path, "rb") as f:
                    try:
                        tag_info.update(pickle.load(f))
                    except Exception as e:
                        log.debug("Unable to load tag info from file: {}".format(path))
                    else:
                        log.debug("Loaded pickled tag info from {}".format(path))
        else:
            log.error("Invalid path: {}".format(path))

    # tbl = Table(
    #     SimpleColumn("Hash"), SimpleColumn("Tag"), SimpleColumn("Tag Name"), SimpleColumn("Value"), update_width=True
    # )
    # rows = []
    # for sha256sum, tags in tag_info.items():
    #     for tag, val in tags.items():
    #         tag = tag[:4]
    #         rows.append({
    #             "Hash": sha256sum, "Tag": tag, "Value": tag_repr(val), "Tag Name": tag_name_map.get(tag, "[unknown]")
    #         })
    # tbl.print_rows(rows)

    return tag_info


def tagless_sha256sum(music_file):
    with open(music_file.filename, "rb") as f:
        tmp = BytesIO(f.read())

    try:
        mutagen.File(tmp).tags.delete(tmp)
    except AttributeError as e:
        log.error("Error determining tagless sha256sum for {}: {}".format(music_file.filename, e))
        return music_file.filename

    tmp.seek(0)
    return sha256(tmp.read()).hexdigest()


def iter_music_files(paths, include_backups=False):
    for path in paths:
        if os.path.isdir(path):
            for root, dirs, files in os.walk(path):
                for f in files:
                    file_path = os.path.join(root, f)
                    try:
                        music_file = mutagen.File(file_path)
                    except Exception as e:
                        log.debug("Error loading {}: {}".format(file_path, e))
                        music_file = None

                    if music_file:
                        yield music_file
                    else:
                        if include_backups:
                            found_backup = False
                            for sha256sum, tags in load_tags(file_path).items():
                                found_backup = True
                                yield FakeMusicFile(sha256sum, tags)
                            if not found_backup:
                                log.debug("Not a music file: {}".format(file_path))
                        else:
                            log.debug("Not a music file: {}".format(file_path))
        elif os.path.isfile(path):
            try:
                music_file = mutagen.File(path)
            except Exception as e:
                log.debug("Error loading {}: {}".format(path, e))
                music_file = None

            if music_file:
                yield music_file
            else:
                if include_backups:
                    found_backup = False
                    for sha256sum, tags in load_tags(path).items():
                        found_backup = True
                        yield FakeMusicFile(sha256sum, tags)
                    if not found_backup:
                        log.debug("Not a music file: {}".format(path))
                else:
                    log.debug("Not a music file: {}".format(path))
        else:
            log.error("Invalid path: {}".format(path))


def tag_repr(tag_val, max_len=125, sub_len=25, use_grapheme=False):
    if not isinstance(tag_val, str):
        tag_val = str(tag_val)
    tag_val = tag_val.translate(WHITESPACE_TRANS_TBL)
    val_len = grapheme.length(tag_val) if use_grapheme else len(tag_val)
    if val_len > max_len:
        if use_grapheme:
            return "{}...{}".format(grapheme.slice(tag_val, 0, sub_len), grapheme.slice(tag_val, val_len - sub_len))
        else:
            return "{}...{}".format(tag_val[:sub_len], tag_val[-sub_len:])
    return tag_val


def remove_tags(paths, tag_ids, dry_run):
    prefix, verb = ("[DRY RUN] ", "Would remove") if dry_run else ("", "Removing")

    tag_ids = sorted({tag_id.upper() for tag_id in tag_ids})
    log.info("{}{} the following tags from all files:".format(prefix, verb))
    for tag_id in tag_ids:
        log.info("\t{}: {}".format(tag_id, tag_name_map.get(tag_id, "[unknown]")))

    i = 0
    for music_file in iter_music_files(paths):
        to_remove = {}
        for tag_id in tag_ids:
            file_tags = music_file.tags.getall(tag_id)
            if file_tags:
                to_remove[tag_id] = file_tags

        if to_remove:
            if i:
                log.debug("")
            rm_str = ", ".join(
                "{}: {}".format(tag_id, tag_repr(val, use_grapheme=True))
                for tag_id, vals in sorted(to_remove.items())
                for val in vals
            )
            info_str = ", ".join("{} ({})".format(tag_id, len(vals)) for tag_id, vals in sorted(to_remove.items()))

            log.info("{}{}: {} tags: {}".format(prefix, music_file.filename, verb, info_str))
            log.debug("\t{}: {}".format(music_file.filename, rm_str))

            if not dry_run:
                for tag_id in to_remove:
                    music_file.tags.delall(tag_id)
                music_file.tags.save(music_file.filename)
            i += 1
        else:
            log.debug("{}: Did not have the tags specified for removal".format(music_file.filename))

    if not i:
        log.info("None of the provided files had the specified tags")


def print_song_tags(paths, tags):
    tags = {tag.upper() for tag in tags} if tags else None
    i = 0
    for music_file in iter_music_files(paths, include_backups=True):
        if i:
            print()
        print("{} (ID3v{}.{}):".format(music_file.filename, *music_file.tags.version[:2]))
        tbl = Table(SimpleColumn("Tag"), SimpleColumn("Tag Name"), SimpleColumn("Value"), update_width=True)
        rows = []
        for tag, val in sorted(music_file.tags.items()):
            if len(tag) > 4:
                tag = tag[:4]

            if not tags or (tag in tags):
                val = str(val)
                rows.append({
                    "Tag": tag,
                    "Tag Name": tag_name_map.get(tag, "[unknown]"),
                    "Value": tag_repr(val)
                })
        if rows:
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
            for pattern in include:
                if fnmatch(tag, pattern):
                    unique_vals[tag][str(val)] += 1
                    break

    tbl = Table(
        SimpleColumn("Tag"), SimpleColumn("Tag Name"), SimpleColumn("Count", align=">", ftype=",d"),
        SimpleColumn("Value"), update_width=True
    )
    rows = []

    for tag, val_counter in unique_vals.items():
        for val, count in val_counter.items():
            rows.append({
                "Tag": tag, "Tag Name": tag_name_map.get(tag, "[unknown]"), "Count": count,
                "Value": tag_repr(val, use_grapheme=True)
            })
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
