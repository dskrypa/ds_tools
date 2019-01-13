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

- Cleanup lyric content to remove url from end if present (example: in CLC/Crystyle/Hobgoblin)

:author: Doug Skrypa
"""

import json
import logging
import os
import pickle
import re
import string
import sys
from collections import Counter, defaultdict
from fnmatch import fnmatch, translate as fnpat2re
from unicodedata import normalize

import mutagen
import mutagen.id3._frames
from mutagen.id3 import ID3, TDRC, TIT2
from mutagen.id3._frames import Frame
from mutagen.mp4 import AtomDataType, MP4Cover, MP4FreeForm, MP4Tags

_script_path = os.path.abspath(__file__)
if os.path.islink(_script_path):
    _link_path = os.readlink(_script_path)
    if _link_path.startswith(".."):
        _script_path = os.path.abspath(os.path.join(os.path.dirname(_script_path), _link_path))
    else:
        _script_path = os.path.abspath(_link_path)
sys.path.append(os.path.dirname(os.path.dirname(_script_path)))
from ds_tools.logging import LogManager
from ds_tools.music import iter_music_files, load_tags, iter_music_albums, iter_categorized_music_files
from ds_tools.music.wiki import Artist, Album
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


def parser():
    parser = ArgParser(description="Music Manager")

    info_parser = parser.add_subparser("action", "info", help="Get song/tag information")
    info_parser.add_argument("path", nargs="+", help="One or more file/directory paths that contain music files")
    info_group = info_parser.add_mutually_exclusive_group()
    info_group.add_argument("--meta_only", "-m", action="store_true", help="Only show song metadata")
    info_group.add_argument("--count", "-c", action="store_true", help="Count tag types rather than printing all info")
    info_group.add_argument("--unique", "-u", metavar="TAGID", nargs="+", help="Count unique values of the specified tag(s)")
    info_group.add_argument("--tags", "-t", nargs="+", help="Filter tags to display in file info mode")
    info_group.add_argument("--table", "-T", action="store_true", help="Print a full table instead of individual tables per file")
    info_group.add_argument("--tag_table", "-TT", nargs="+", help="Print a table comparing the specified tag IDs across each file")

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

    list_parser = parser.add_subparser("action", "list", help="TEMP")
    list_parser.add_argument("path", help="A directory that contains directories that contain music files")

    auto_parser = parser.add_subparser("action", "auto", help="Automatically perform the most common tasks")
    auto_parser.add_argument("path", help="A directory that contains directories that contain music files")

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
        elif args.tag_table:
            table_song_tags(args.path, args.tag_table)
        else:
            print_song_tags(args.path, args.tags, args.meta_only)
    elif args.action == "auto":
        remove_tags(args.path, None, args.dry_run, True)    # remove . -r
        fix_tags(args.path, args.dry_run)                   # fix .
        sort_albums(args.path, args.dry_run)                # sort .
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
    elif args.action == "list":
        tools_dir = os.path.dirname(os.path.dirname(_script_path))
        with open(os.path.join(tools_dir, "music", "artist_dir_to_artist.json"), "r", encoding="utf-8") as f:
            dir2artist = json.load(f)

        for _dir, disp_name in sorted(dir2artist.items()):
            if not disp_name:
                artist_dir = os.path.join(args.path, _dir)
                if os.path.exists(artist_dir):
                    for mfile in iter_music_files(artist_dir):
                        try:
                            artist = mfile.tags["TPE1"].text[0]
                        except KeyError as e:
                            pass
                        else:
                            if "," not in artist:
                                print("\"{}\": \"{}\",".format(_dir, artist))
                                break
                else:
                    print("\"{}\": \"{}\",".format(_dir, ""))
            else:
                print("\"{}\": \"{}\",".format(_dir, disp_name))
    else:
        log.error("Unconfigured action")


def path2tag(path, dry_run, incl_title):
    # TODO: Add prompt / default yes for individual files
    prefix = "[DRY RUN] Would update" if dry_run else "Updating"

    for music_file in iter_music_files(path):
        try:
            title_key = music_file.tag_name_to_id("title")
        except KeyError as e:
            log.warning("Skipping due to unhandled file type: {}".format(music_file.filename))
            continue

        try:
            titles = music_file.tags[title_key].text
        except Exception as e:
            log.error("Error retrieving title for {} - {}".format(music_file.filename, e))
            continue
        else:
            if len(titles) > 1:
                log.warning("Skipping {} - More than 1 title value".format(music_file.filename))
                continue
            title = titles[0]

        filename = music_file.basename(True, True)
        if incl_title and (title != filename):
            log.info("{} the title of {} from {!r} to {!r}".format(prefix, music_file.filename, title, filename))
            if not dry_run:
                music_file.tags[title_key] = filename if (music_file.file_type == "mp4") else TIT2(text=filename)
                music_file.tags.save(music_file.filename)
        else:
            log.log(19, "Skipping file with already correct title: {}".format(music_file.filename))


def sort_albums(path, dry_run):
    """
    Sort albums in the given path by album type

    :param str path: Path to the directory to sort
    :param bool dry_run: Print the actions that would be taken instead of taking them
    """
    prefix, verb = ("[DRY RUN] ", "Would rename") if dry_run else ("", "Renaming")
    punc_strip_tbl = str.maketrans({c: "" for c in string.punctuation})

    for parent_dir, album_dir, music_files in iter_music_albums(path):
        if not album_dir.startswith("["):
            album_path = os.path.join(parent_dir, album_dir)
            dates = set()
            skip_dir = False
            for music_file in music_files:
                try:
                    date_tag = music_file.tag_named("date")
                except KeyError as e:
                    log.warning("Skipping dir due to problem finding date for {} - {}".format(music_file.filename, e))
                    skip_dir = True
                    break
                else:
                    date_tag_val = str(getattr(date_tag, "text", date_tag)[0]).strip()
                    if date_tag_val:
                        dates.add(date_tag_val)

            if skip_dir:
                continue
            elif len(dates) == 1:
                date_str = dates.pop().translate(punc_strip_tbl)[:8]
                date_fmt_in = "%Y" if len(date_str) == 4 else "%Y%m%d"
                date_fmt_out = "%Y" if len(date_str) == 4 else "%Y.%m.%d"
                try:
                    album_date = localize(date_str, in_fmt=date_fmt_in, out_fmt=date_fmt_out)
                except Exception:
                    album_date = None
            else:
                log.warning("Unexpected dates found for album '{}': {}".format(album_path, ", ".join(sorted(dates))))
                album_date = None

            if album_date:
                album_dir = "[{}] {}".format(album_date, album_dir)
                new_path = os.path.join(parent_dir, album_dir)
                log.info("[add date] {}{} '{}' -> '{}'".format(prefix, verb, album_path, new_path))
                if not dry_run:
                    os.rename(album_path, new_path)

    numbered_albums = defaultdict(lambda: defaultdict(dict))
    for parent_dir, artist_dir, category_dir, album_dir, music_files in iter_categorized_music_files(path):
        album_path = os.path.join(parent_dir, artist_dir, category_dir, album_dir)
        if (category_dir in ("Albums", "Mini Albums")) and album_dir.startswith("["):
            album_dir_lower = album_dir.lower()
            if any(skip_reason in album_dir_lower for skip_reason in ("summer mini album", "reissue", "repackage")):
                log.debug("Skipping non-standard album: {}".format(album_dir))
                continue
            category = category_dir[:-1]

            files, japanese = 0, 0
            for music_file in music_files:
                files += 1
                _tags = {"genre": [], "title": [], "album": []}
                for tag_name in _tags:
                    _tags[tag_name] = [t.translate(punc_strip_tbl).lower() for t in music_file.all_tag_text(tag_name)]

                if any(i in tag for tag_list in _tags.values() for tag in tag_list for i in ("jpop", "japanese")):
                    japanese += 1

            log.debug("{}: Japanese: {:.2%}".format(album_path, japanese / files))
            if japanese / files >= .45:
                category = "Japanese {}".format(category)

            num = len(numbered_albums[artist_dir][category]) + 1
            numbered_albums[artist_dir][category][num] = album_path

    for artist_dir, categorized_albums in sorted(numbered_albums.items()):
        for cat, albums in sorted(categorized_albums.items()):
            for num, _path in sorted(albums.items()):
                if not _path.endswith("]"):
                    parent_dir, album_dir = os.path.split(_path)
                    album_dir = "{} [{}{} {}]".format(album_dir, num, num_suffix(num), cat)
                    new_path = os.path.join(parent_dir, album_dir)
                    log.info("[Number within category] {}{} '{}' -> '{}'".format(prefix, verb, _path, new_path))
                    if not dry_run:
                        os.rename(_path, new_path)
                else:
                    log.log(19, "Album already has correct name: {}".format(_path))

    for parent_dir, artist_dir, category_dir, album_dir, music_files in iter_categorized_music_files(path):
        album_path = os.path.join(parent_dir, artist_dir, category_dir, album_dir)
        pat = "^(\[[^\]]+\])?\s*" + artist_dir + "\s*-?\s*(.*)$"
        m = re.match(pat, album_dir)
        if m:
            date_prefix = m.group(1)
            album_name = m.group(2).strip()
            new_album_dir = album_name if not date_prefix else "{} {}".format(date_prefix, album_name)
            # new_album_dir = m.group(1).strip()
            if new_album_dir:
                new_album_path = os.path.join(parent_dir, artist_dir, category_dir, new_album_dir)
                if new_album_path != album_path:
                    log.info("[Remove artist from album dir name] {}{} '{}' -> '{}'".format(prefix, verb, album_path, new_album_path))
                    if not dry_run:
                        os.rename(album_path, new_album_path)


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
    prefix, add_msg, rmv_msg = ("[DRY RUN] ", "Would add", "remove") if dry_run else ("", "Adding", "removing")
    upd_msg = "Would update" if dry_run else "Updating"

    for music_file in iter_music_files(paths):
        if not isinstance(music_file.tags, ID3):
            log.debug("Skipping non-MP3: {}".format(music_file.filename))
            continue

        tdrc = music_file.tags.getall("TDRC")
        txxx_date = music_file.tags.getall("TXXX:DATE")
        if (not tdrc) and txxx_date:
            file_date = txxx_date[0].text[0]

            log.info("{}{} TDRC={} to {} and {} its TXXX:DATE tag".format(prefix, add_msg, file_date, music_file.filename, rmv_msg))
            if not dry_run:
                music_file.tags.add(TDRC(text=file_date))
                music_file.tags.delall("TXXX:DATE")
                music_file.tags.save(music_file.filename)

        lyrics_tags = music_file.tags.getall("USLT")
        if len(lyrics_tags) == 1:
            lyrics_tag = lyrics_tags[0]
            m = re.match("^(.*)(https?://\S+)$", lyrics_tag.text, re.DOTALL)
            if m:
                new_lyrics = m.group(1).strip() + "\r\n"
                log.info("{}{} lyrics for {} from {!r} to {!r}".format(prefix, upd_msg, music_file.filename, tag_repr(lyrics_tag.text), tag_repr(new_lyrics)))
                if not dry_run:
                    lyrics_tag.text = new_lyrics
                    music_file.tags.save(music_file.filename)

    for parent_dir, artist_dir, category_dir, album_dir, music_files in iter_categorized_music_files(paths):
        for music_file in music_files:
            wiki_artist = Artist(artist_dir)
            try:
                album_name = music_file.album_name_cleaned
            except KeyError as e:
                log.error("Error retrieving album for {}".format(music_file))
                raise e

            song_title = music_file.tag_title
            wiki_album = wiki_artist.find_album(album_name)
            if wiki_album is None:
                artist = music_file.tag_artist
                m = re.match("(.+?)\s*\(.*", artist)
                if m:
                    wiki_artist = Artist(m.group(1))
                    wiki_album = wiki_artist.find_album(album_name)

            if wiki_album is not None:
                song = wiki_album.find_track(song_title)
                if song:
                    # log.info("{!r} - {!r} - {!r} ==> {}".format(music_file.tag_artist, album_name, song_title, song))
                    if (song_title.lower() != song.file_title.lower()) and not song_title.lower().startswith(song.file_title.lower()):
                        log.info("{}{} {!r} - {!r} - {!r} ==> {!r} / {}".format(prefix, upd_msg, music_file.tag_artist, album_name, song_title, song.file_title, song))
                        try:
                            title_key = music_file.tag_name_to_id("title")
                        except KeyError as e:
                            log.warning("Skipping due to unhandled file type: {}".format(music_file.filename))
                            continue

                        if not dry_run:
                            music_file.tags[title_key] = song.file_title if (music_file.file_type == "mp4") else TIT2(text=song.file_title)
                            music_file.tags.save(music_file.filename)
                    else:
                        log.log(19, "No changes necessary for {!r} - {!r} - {!r} == {!r} / {}".format(music_file.tag_artist, album_name, song_title, song.file_title, song))
                else:
                    log.debug("Unable to find song match for {!r} - {!r} - {!r}  /  {}".format(music_file.tag_artist, album_name, song_title, music_file))
            else:
                log.debug("Unable to find album match for {!r} - {!r} - {!r}  /  {}".format(music_file.tag_artist, album_name, song_title, music_file))
                # log.info("Unable to find match for {!r} - {!r} - {!r}".format(music_file.tag_artist, album_name, song_title))
                # log.info("Unable to find {} album matching {}".format(wiki_artist, album_name))


def copy_tags(source_paths, dest_paths, tags, dry_run):
    if not tags:
        raise ValueError("One or more tags or 'ALL' must be specified for --tags/-t")
    tags = sorted({tag.upper() for tag in tags})
    all_tags = "ALL" in tags
    src_tags = load_tags(source_paths)

    prefix, verb = ("[DRY RUN] ", "Would update") if dry_run else ("", "Updating")

    for music_file in iter_music_files(dest_paths):
        path = music_file.filename
        content_hash = music_file.tagless_sha256sum()
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

    tag_info = load_tags([backup_path]) if os.path.isfile(backup_path) else {}
    for i, music_file in enumerate(iter_music_files(source_paths, include_backups=True)):
        content_hash = music_file.tagless_sha256sum()
        log.debug("{}: {}".format(music_file.filename, content_hash))
        tag_info[content_hash] = music_file.tags

    with open(backup_path, "wb") as f:
        log.info("Writing tag info to: {}".format(backup_path))
        pickle.dump(tag_info, f)


def tag_repr(tag_val, max_len=125, sub_len=25):
    tag_val = normalize("NFC", str(tag_val)).translate(WHITESPACE_TRANS_TBL)
    if len(tag_val) > max_len:
        return "{}...{}".format(tag_val[:sub_len], tag_val[-sub_len:])
    return tag_val


def remove_tags(paths, tag_ids, dry_run, recommended):
    prefix, verb = ("[DRY RUN] ", "Would remove") if dry_run else ("", "Removing")

    # tag_ids = sorted({tag_id.upper() for tag_id in tag_ids})
    tag_id_pats = sorted({tag_id for tag_id in tag_ids}) if tag_ids else []
    if tag_id_pats:
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
                "{}: {}".format(tag_id, tag_repr(val)) for tag_id, vals in sorted(to_remove.items()) for val in vals
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


def table_song_tags(paths, include_tags=None):
    rows = [TableBar()]
    tags = set()
    for music_file in iter_music_files(paths, include_backups=True):
        row = defaultdict(str, path=music_file.filename)
        for tag, val in sorted(music_file.tags.items()):
            tag = ":".join(tag.split(":")[:2])
            if (include_tags is None) or (tag in include_tags):
                tags.add(tag)
                row[tag] = tag_repr(str(val), 10, 5) if tag.startswith("APIC") else tag_repr(str(val))
        rows.append(row)

    desc_row = {tag: tag_name_map.get(tag[:4], "[unknown]") for tag in tags}
    desc_row["path"] = "[Tag Description]"
    rows.insert(0, desc_row)
    cols = [SimpleColumn(tag) for tag in sorted(tags)]
    tbl = Table(SimpleColumn("path"), *cols, update_width=True)
    tbl.print_rows(rows)


def print_song_tags(paths, tags, meta_only=False):
    tags = {tag.upper() for tag in tags} if tags else None
    for i, music_file in enumerate(iter_music_files(paths, include_backups=True)):
        if i and not meta_only:
            print()

        if isinstance(music_file.tags, MP4Tags):
            print("{} [{}] (MP4):".format(music_file.filename, music_file.length_str))
        elif isinstance(music_file.tags, ID3):
            print("{} [{}] (ID3v{}.{}):".format(music_file.filename, music_file.length_str, *music_file.tags.version[:2]))
        else:
            raise TypeError("Unhandled tag type: {}".format(type(music_file.tags).__name__))

        if meta_only:
            continue

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
                "Tag": tag, "Tag Name": tag_name_map.get(tag, "[unknown]"), "Count": count, "Value": tag_repr(val)
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
