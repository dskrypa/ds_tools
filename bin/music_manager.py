#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Manage music files


Example usage - List unique tags in the current directory, filtering out known tags::

    $ /c/unix/home/user/git/ds_tools/bin/music_manager.py info . -u '*' | egrep -v 'TIT2|TALB|TCON|TRCK|USLT|APIC|TDRC|TPE1|TPOS|TPE2|nam  \[|wrt  \[|TCOM|trkn|sonm|alb  \[|soa[alr]  \[ |ART  \[|day  \['

Example usage - Remove recommended tags from files in the current directory::

    $ /c/unix/home/user/git/ds_tools/bin/music_manager.py remove . -r


TODO:
- Implement AcoustID scanning or whatever audio fingerprinting method is current, and have a mapping of detected artist => preferred artist name for renaming artist tags?
- Look up artist wiki discography to sort directories by album type
    - Use generic / genre-specific wikis, such as http://kpop.wikia.com/wiki/$artist
    - Can use this to append '[Xth [$lang] [Mini] Album]' suffixes
- Remove artist from '[$date] $artist - $album' directory names
- Provide way to replace tag values with a provided value

- Cleanup lyric content to remove url from end if present (example: in CLC/Crystyle/Hobgoblin)

:author: Doug Skrypa
"""

import logging
import os
import pickle
import re
import string
import sys
from collections import Counter, defaultdict
from contextlib import suppress
from fnmatch import fnmatch, translate as fnpat2re
from hashlib import sha256
from io import BytesIO

import grapheme
import mutagen
import mutagen.id3._frames
from mutagen.id3 import ID3, TDRC, TIT2
from mutagen.id3._frames import Frame
from mutagen.mp4 import AtomDataType, MP4Cover, MP4FreeForm, MP4Tags

_file_path = os.path.abspath(__file__)
if os.path.islink(_file_path):
    _link_path = os.readlink(_file_path)
    if _link_path.startswith(".."):
        _file_path = os.path.abspath(os.path.join(os.path.dirname(_file_path), _link_path))
    else:
        _file_path = os.path.abspath(_link_path)
sys.path.append(os.path.dirname(os.path.dirname(_file_path)))
from ds_tools.logging import LogManager
from ds_tools.utils import Table, SimpleColumn, localize, TableBar, num_suffix, ArgParser
from music.constants import tag_name_map

log = logging.getLogger("ds_tools.{}".format(__name__))

# Translate whitespace characters (such as \n, \r, etc.) to their escape sequences
WHITESPACE_TRANS_TBL = str.maketrans({c: c.encode("unicode_escape").decode("utf-8") for c in string.whitespace})
RM_TAGS_MP4 = ["*itunes*", "??ID", "?cmt", "ownr", "xid ", "purd"]
RM_TAGS_ID3 = ["TXXX*", "PRIV*", "WXXX*", "COMM*", "TCOP"]

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

_orig_reprs = {}

def _MP4Cover_repr(self):
    return "{}({}, {})".format(type(self).__name__, tag_repr(bytes(self), 10, 5), AtomDataType(self.imageformat))

def _MP4FreeForm_repr(self):
    return "{}({}, {})".format(type(self).__name__, tag_repr(bytes(self), 10, 5), AtomDataType(self.dataformat))

for cls in (MP4Cover, MP4FreeForm):
    _orig_reprs[cls] = cls.__repr__

MP4Cover.__repr__ = _MP4Cover_repr
MP4FreeForm.__repr__ = _MP4FreeForm_repr


class FakeMusicFile:
    def __init__(self, sha256sum, tags):
        self.filename = sha256sum
        self.tags = tags


def parser():
    parser = ArgParser(description="Music Manager")

    info_parser = parser.add_subparser("action", "info", help="Get song/tag information")
    info_parser.add_argument("path", nargs="+", help="One or more file/directory paths that contain music files")
    info_group = info_parser.add_mutually_exclusive_group()
    info_group.add_argument("--count", "-c", action="store_true", help="Count tag types rather than printing all info")
    info_group.add_argument("--unique", "-u", metavar="TAGID", nargs="+", help="Count unique values of the specified tag(s)")
    info_group.add_argument("--tags", "-t", nargs="+", help="Filter tags to display in file info mode")
    info_group.add_argument("--table", "-T", action="store_true", help="Print a full table instead of individual tables per file")

    rm_parser = parser.add_subparser("action", "remove", help="Remove specified tags from the given files")
    rm_parser.add_argument("path", nargs="+", help="One or more file/directory paths that contain music files")
    rm_group = rm_parser.add_mutually_exclusive_group()
    rm_group.add_argument("--tags", "-t", nargs="+", help="One or more tag IDs to remove from the given files")
    rm_group.add_argument("--recommended", "-r", action="store_true", help="Remove recommended tags")

    cp_parser = parser.add_subparser("action", "copy", help="Copy specified tags from one set of files to another")
    cp_parser.add_argument("--source", "-s", nargs="+", help="One or more file/directory paths that contain music files or ID3 info backups", required=True)
    cp_parser.add_argument("--dest", "-d", nargs="+", help="One or more file/directory paths that contain music files, or a path to store an ID3 info backup")
    cp_parser.add_argument("--backup", "-b", action="store_true", help="Store a backup of ID3 information instead of writing directly to matching music files")
    cp_parser.add_argument("--tags", "-t", nargs="+", help="One or more tag IDs to copy to the destination files")

    fix_parser = parser.add_subparser("action", "fix", help="Fix poorly chosen tags in the given files (such as TXXX:DATE, etc)")
    fix_parser.add_argument("path", nargs="+", help="One or more file/directory paths that contain music files")

    sort_parser = parser.add_subparser("action", "sort", help="Sort music into directories based on tag info")
    sort_parser.add_argument("path", help="A directory that contains directories that contain music files")

    p2t_parser = parser.add_subparser("action", "path2tag", help="Update tags based on the path to each file")
    p2t_parser.add_argument("path", help="A directory that contains directories that contain music files")
    p2t_parser.add_argument("--title", "-t", action="store_true", help="Update title based on filename")

    set_parser = parser.add_subparser("action", "set", help="Set the value of the given tag on all music files in the given path")
    set_parser.add_argument("path", nargs="+", help="One or more file/directory paths that contain music files")
    set_parser.add_argument("--tag", "-t", nargs="+", help="Tag ID(s) to modify", required=True)
    set_parser.add_argument("--value", "-V", help="Value to replace existing values with", required=True)
    set_parser.add_argument("--replace", "-r", nargs="+", help="If specified, only replace tag values that match the given patterns(s)")
    set_parser.add_argument("--partial", "-p", action="store_true", help="Update only parts of tags that match a pattern specified via --replace/-r")

    parser.include_common_args("verbosity", "dry_run")
    return parser


def main():
    args = parser().parse_args()
    LogManager.create_default_logger(args.verbose, log_path=None)

    if args.action == "info":
        if args.count:
            count_tag_types(args.path)
        elif args.unique:
            count_unique_vals(args.path, args.unique)
        elif args.table:
            table_song_tags(args.path)
        else:
            print_song_tags(args.path, args.tags)
    elif args.action == "remove":
        remove_tags(args.path, args.tags, args.dry_run, args.recommended)
    elif args.action == "fix":
        fix_tags(args.path, args.dry_run)
    elif args.action == "copy":
        if args.backup:
            if len(args.dest) > 1:
                raise ValueError("Only one --dest/-d path may be provided in backup mode")
            save_tag_backups(args.source, args.dest)
        else:
            copy_tags(args.source, args.dest, args.tags, args.dry_run)
    elif args.action == "sort":
        sort_albums(args.path, args.dry_run)
    elif args.action == "path2tag":
        path2tag(args.path, args.dry_run, args.title)
    elif args.action == "set":
        set_tags(args.path, args.tag, args.value, args.replace, args.partial, args.dry_run)
    else:
        log.error("Unconfigured action")


def path2tag(path, dry_run, incl_title):
    # TODO: Add prompt / default yes for individual files
    prefix = "[DRY RUN] Would update" if dry_run else "Updating"
    punc_strip_tbl = str.maketrans({c: "" for c in string.punctuation})
    filename_rx = re.compile("\d+\.\s+(.*)")

    for root, dirs, files in os.walk(path):
        parent_dir = os.path.dirname(root)
        artist_dir = os.path.dirname(parent_dir)
        album_dir = os.path.basename(root)
        category_dir = os.path.basename(parent_dir)

        for music_file in iter_music_files(root):
            filename = os.path.splitext(os.path.basename(music_file.filename))[0]
            m = filename_rx.match(filename)
            if m:
                filename = m.group(1)

            if isinstance(music_file.tags, MP4Tags):
                title_key = "\xa9nam"
                ftype = "mp4"
            elif isinstance(music_file.tags, ID3):
                title_key = "TIT2"
                ftype = "mp3"
            else:
                log.warning("Skipping {}: Unhandled filetype".format(music_file.filename))
                continue

            try:
                title = music_file.tags[title_key].text[0]
            except Exception as e:
                log.error("{}: Error retrieving title: {}".format(music_file.filename, e))
                continue
            else:
                if len(music_file.tags[title_key].text) > 1:
                    log.warning("Skipping {}: More than 1 title value".format(music_file.filename))
                    continue

            if incl_title and (title != filename):
                log.info("{} the title of {} from {!r} to {!r}".format(prefix, music_file.filename, title, filename))
                if not dry_run:
                    music_file.tags[title_key] = filename if (ftype == "mp4") else TIT2(text=filename)
                    music_file.tags.save(music_file.filename)
            else:
                log.info("The title of {} is already correct".format(music_file.filename))


def sort_albums(path, dry_run):
    """
    Sort albums in the given path by album type

    :param str path: Path to the directory to sort
    :param bool dry_run: Print the actions that would be taken instead of taking them
    """
    prefix, verb = ("[DRY RUN] ", "Would rename") if dry_run else ("", "Renaming")
    punc_strip_tbl = str.maketrans({c: "" for c in string.punctuation})

    for root, dirs, files in os.walk(path):
        parent_dir = os.path.dirname(root)
        album_dir = os.path.basename(root)
        if files and (not dirs) and (not album_dir.startswith("[")):
            dates = set()
            skip_dir = False
            for music_file in iter_music_files(root):
                if isinstance(music_file.tags, MP4Tags):
                    date_tag = str(music_file.tags["\xa9day"][0]).strip()
                    if date_tag:
                        dates.add(date_tag)
                elif isinstance(music_file.tags, ID3):
                    try:
                        date_tag = str(music_file.tags["TDRC"].text[0]).strip()
                        if date_tag:
                            dates.add(date_tag)
                    except KeyError as e:
                        log.warning("Skipping dir with missing TDRC in file: {}".format(music_file.filename))
                        skip_dir = True
                        break
                else:
                    log.warning("Skipping dir with unhandled file type: {} ({})".format(root, type(music_file.tags).__name__))
                    skip_dir = True
                    break

            if skip_dir:
                continue

            if len(dates) == 1:
                date_str = dates.pop().translate(punc_strip_tbl)[:8]
                date_fmt_in = "%Y" if len(date_str) == 4 else "%Y%m%d"
                date_fmt_out = "%Y" if len(date_str) == 4 else "%Y.%m.%d"
                try:
                    album_date = localize(date_str, in_fmt=date_fmt_in, out_fmt=date_fmt_out)
                except Exception:
                    album_date = None
            else:
                log.warning("Unexpected dates found for album '{}': {}".format(root, ", ".join(sorted(dates))))
                album_date = None

            if album_date:
                album_dir = "[{}] {}".format(album_date, album_dir)
                new_path = os.path.join(parent_dir, album_dir)
                log.info("{}{} '{}' -> '{}'".format(prefix, verb, root, new_path))
                if not dry_run:
                    os.rename(root, new_path)

    numbered_albums = defaultdict(lambda: defaultdict(dict))

    for root, dirs, files in os.walk(path):
        parent_dir = os.path.dirname(root)
        artist_dir = os.path.dirname(parent_dir)
        album_dir = os.path.basename(root)
        category_dir = os.path.basename(parent_dir)

        if (category_dir in ("Albums", "Mini Albums")) and files and album_dir.startswith("["):
            album_dir_lower = album_dir.lower()
            if any(skip_reason in album_dir_lower for skip_reason in ("summer mini album", "reissue", "repackage")):
                log.debug("Skipping non-standard album: {}".format(album_dir))
                continue
            category = category_dir[:-1]

            files, japanese = 0, 0
            for music_file in iter_music_files(root):
                files += 1
                gkey, tkey = None, None
                if isinstance(music_file.tags, MP4Tags):
                    gkey, tkey = "\xa9gen", "\xa9nam"
                elif isinstance(music_file.tags, ID3):
                    gkey, tkey = "TCON", "TIT2"

                genre_tags, title_tags = [], []
                if all(k is not None for k in (gkey, tkey)):
                    with suppress(KeyError):
                        genre_tags = [t.translate(punc_strip_tbl).lower() for t in music_file.tags[gkey]]
                    with suppress(KeyError):
                        title_tags = [t.translate(punc_strip_tbl).lower() for t in music_file.tags[tkey]]

                if any("jpop" in t for t in genre_tags) or any("japanese" in t for t in title_tags):
                    japanese += 1

            log.debug("{}: Japanese: {:.2%}".format(root, japanese / files))
            if japanese / files >= .45:
                category = "Japanese {}".format(category)

            num = len(numbered_albums[artist_dir][category]) + 1
            numbered_albums[artist_dir][category][num] = root

    for artist_dir, categorized_albums in sorted(numbered_albums.items()):
        for cat, albums in sorted(categorized_albums.items()):
            for num, path in sorted(albums.items()):
                if not path.endswith("]"):
                    parent_dir = os.path.dirname(path)
                    album_dir = os.path.basename(path)
                    album_dir = "{} [{}{} {}]".format(album_dir, num, num_suffix(num), cat)
                    new_path = os.path.join(parent_dir, album_dir)
                    log.info("{}{} '{}' -> '{}'".format(prefix, verb, path, new_path))
                    if not dry_run:
                        os.rename(path, new_path)
                else:
                    log.info("Album already has correct name: {}".format(path))


def set_tags(paths, tag_ids, value, replace_pats, partial, dry_run):
    prefix, repl_msg, set_msg = ("[DRY RUN] ", "Would replace", "Would set") if dry_run else ("", "Replacing", "Setting")
    repl_rxs = [re.compile(fnpat2re(pat)[4:-3]) for pat in replace_pats] if replace_pats else []
    if partial and not repl_rxs:
        raise ValueError("When using --partial/-p, --replace/-r must also be specified")

    for music_file in iter_music_files(paths):
        if not isinstance(music_file.tags, ID3):
            log.debug("Skipping non-MP3: {}".format(music_file.filename))
            continue

        should_save = False
        for tag_id in tag_ids:
            tag_name = tag_name_map.get(tag_id)
            if not tag_name:
                raise ValueError("Invalid tag ID: {}".format(tag_id))

            current_vals = music_file.tags.getall(tag_id)
            if not current_vals:
                try:
                    fcls = getattr(mutagen.id3._frames, tag_id.upper())
                except AttributeError as e:
                    raise ValueError("Invalid tag ID: {} (no frame class found for it)".format(tag_id)) from e

                log.info("{}{} {}/{} = '{}' in file: {}".format(prefix, set_msg, tag_id, tag_name, value, music_file.filename))
                should_save = True
                if not dry_run:
                    music_file.tags.add(fcls(text=value))
            else:
                if len(current_vals) > 1:
                    log.warning("Skipping file with multiple values for {}/{}: {}".format(tag_id, tag_name, music_file.filename))

                current_val = current_vals[0]
                current_text = current_val.text[0]
                new_text = current_text
                if partial:
                    for rx in repl_rxs:
                        new_text = rx.sub(value, new_text)
                else:
                    if repl_rxs:
                        if any(rx.search(current_text) for rx in repl_rxs):
                            new_text = value
                    else:
                        new_text = value

                if new_text != current_text:
                    log.info("{}{} {}/{} {!r} with {!r} in {}".format(prefix, repl_msg, tag_id, tag_name, current_text, new_text, music_file.filename))
                    should_save = True
                    if not dry_run:
                        current_vals[0].text[0] = new_text

        if should_save:
            if not dry_run:
                music_file.tags.save(music_file.filename)
        else:
            log.log(19, "Nothing to change for {}".format(music_file.filename))


def fix_tags(paths, dry_run):
    # TODO: Convert ` to '
    prefix, verb1, verb2 = ("[DRY RUN] ", "Would add", "remove") if dry_run else ("", "Adding", "removing")

    for music_file in iter_music_files(paths):
        if not isinstance(music_file.tags, ID3):
            log.debug("Skipping non-MP3: {}".format(music_file.filename))
            continue

        tdrc = music_file.tags.getall("TDRC")
        txxx_date = music_file.tags.getall("TXXX:DATE")
        if (not tdrc) and txxx_date:
            file_date = txxx_date[0].text[0]

            log.info("{}{} TDRC={} to {} and {} its TXXX:DATE tag".format(prefix, verb1, file_date, music_file.filename, verb2))
            if not dry_run:
                music_file.tags.add(TDRC(text=file_date))
                music_file.tags.delall("TXXX:DATE")
                music_file.tags.save(music_file.filename)


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
    if isinstance(paths, str):
        paths = [paths]

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


def remove_tags(paths, tag_ids, dry_run, recommended):
    prefix, verb = ("[DRY RUN] ", "Would remove") if dry_run else ("", "Removing")

    # tag_ids = sorted({tag_id.upper() for tag_id in tag_ids})
    tag_id_pats = sorted({tag_id for tag_id in tag_ids}) if tag_ids else []
    log.info("{}{} the following tags from all files:".format(prefix, verb))
    if tag_ids:
        for tag_id in tag_ids:
            log.info("\t{}: {}".format(tag_id, tag_name_map.get(tag_id, "[unknown]")))

    i = 0
    for music_file in iter_music_files(paths):
        if isinstance(music_file.tags, MP4Tags):
            if recommended:
                tag_id_pats = RM_TAGS_MP4
            # file_tag_ids = {tag_id.upper(): tag_id for tag_id in music_file.tags}
        elif isinstance(music_file.tags, ID3):
            if recommended:
                tag_id_pats = RM_TAGS_ID3
        else:
            raise TypeError("Unhandled tag type: {}".format(type(music_file.tags).__name__))

        to_remove = {}

        for tag, val in sorted(music_file.tags.items()):
            if any(fnmatch(tag, pat) for pat in tag_id_pats):
                to_remove[tag] = val if isinstance(val, list) else [val]

        # for tag_id in tag_ids:
        #     if isinstance(music_file.tags, MP4Tags):
        #         if tag_id in file_tag_ids:
        #             case_sensitive_tag_id = file_tag_ids[tag_id]
        #             to_remove[case_sensitive_tag_id] = music_file.tags[case_sensitive_tag_id]
        #
        #     elif isinstance(music_file.tags, ID3):
        #         file_tags = music_file.tags.getall(tag_id)
        #         if file_tags:
        #             to_remove[tag_id] = file_tags

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
                    if isinstance(music_file.tags, MP4Tags):
                        del music_file.tags[tag_id]
                    elif isinstance(music_file.tags, ID3):
                        music_file.tags.delall(tag_id)
                music_file.tags.save(music_file.filename)
            i += 1
        else:
            log.debug("{}: Did not have the tags specified for removal".format(music_file.filename))

    if not i:
        log.info("None of the provided files had the specified tags")


def table_song_tags(paths):
    rows = [TableBar()]
    tags = set()
    for music_file in iter_music_files(paths, include_backups=True):
        row = defaultdict(str, path=music_file.filename)
        for tag, val in sorted(music_file.tags.items()):
            tag = ":".join(tag.split(":")[:2])
            tags.add(tag)
            row[tag] = tag_repr(str(val), 10, 5) if tag.startswith("APIC") else tag_repr(str(val))
        rows.append(row)

    desc_row = {tag: tag_name_map.get(tag[:4], "[unknown]") for tag in tags}
    desc_row["path"] = "[Tag Description]"
    rows.insert(0, desc_row)
    cols = [SimpleColumn(tag) for tag in sorted(tags)]
    tbl = Table(SimpleColumn("path"), *cols, update_width=True)
    tbl.print_rows(rows)


def print_song_tags(paths, tags):
    tags = {tag.upper() for tag in tags} if tags else None
    for i, music_file in enumerate(iter_music_files(paths, include_backups=True)):
        if i:
            print()

        if isinstance(music_file.tags, MP4Tags):
            print("{} (MP4):".format(music_file.filename))
        elif isinstance(music_file.tags, ID3):
            print("{} (ID3v{}.{}):".format(music_file.filename, *music_file.tags.version[:2]))
        else:
            raise TypeError("Unhandled tag type: {}".format(type(music_file.tags).__name__))

        tbl = Table(SimpleColumn("Tag"), SimpleColumn("Tag Name"), SimpleColumn("Value"), update_width=True)
        rows = []
        for tag, val in sorted(music_file.tags.items()):
            if len(tag) > 4:
                tag = tag[:4]

            if not tags or (tag in tags):
                rows.append({"Tag": tag, "Tag Name": tag_name_map.get(tag, "[unknown]"), "Value": tag_repr(str(val))})
        if rows:
            tbl.print_rows(rows)


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
        if isinstance(music_file.tags, MP4Tags):
            pass
        elif isinstance(music_file.tags, ID3):
            id3_versions.update(["ID3v{}.{}".format(*music_file.tags.version[:2])])
        else:
            log.warning("{}: Unhandled tag type: {}".format(music_file.filename, type(music_file.tags).__name__))

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
