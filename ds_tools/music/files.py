"""
:author: Doug Skrypa
"""

import logging
import os
import pickle
import re
import string
import traceback
from contextlib import suppress
from fnmatch import fnmatch
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from weakref import WeakValueDictionary

# import acoustid
import mutagen
import mutagen.id3._frames
from fuzzywuzzy import fuzz
from mutagen.id3 import ID3, TDRC, TIT2, TALB, TPE1, POPM
from mutagen.id3._frames import Frame, TextFrame
from mutagen.mp4 import AtomDataType, MP4Cover, MP4FreeForm, MP4Tags

from ..caching import cached, DBCache, CacheKey, ClearableCachedPropertyMixin
from ..core import cached_property, get_user_cache_dir, format_duration
from ..http import CodeBasedRestException
from ..unicode import contains_hangul
# from ..utils import ParentheticalParser
from .patches import tag_repr
from .name_processing import split_names
from .wiki import WikiArtist, WikiEntityIdentificationException
# from .wiki.old import Artist, CollaborationSong, split_name

__all__ = [
    "SongFile", "FakeMusicFile", "iter_music_files", "load_tags", "iter_music_albums",
    "iter_categorized_music_files", "TagException",  "TagAccessException", "UnsupportedTagForFileType",
    "InvalidTagName", "TagValueException", "TagNotFound", "WikiMatchException", "AlbumDir", "iter_album_dirs",
    "RM_TAGS_MP4", "RM_TAGS_ID3"
]
log = logging.getLogger(__name__)

NON_MUSIC_EXTS = {"jpg", "jpeg", "png", "jfif", "part", "pdf", "zip"}
PUNC_STRIP_TBL = str.maketrans({c: "" for c in string.punctuation})
RATING_RANGES = [(1, 31, 15), (32, 95, 64), (96, 159, 128), (160, 223, 196), (224, 255, 255)]
RM_TAGS_MP4 = ["*itunes*", "??ID", "?cmt", "ownr", "xid ", "purd", "desc", "ldes", "cprt"]
RM_TAGS_ID3 = ["TXXX*", "PRIV*", "WXXX*", "COMM*", "TCOP"]
TYPED_TAG_MAP = {   # See: https://wiki.hydrogenaud.io/index.php?title=Tag_Mapping
    "title": {"mp4": "\xa9nam", "mp3": "TIT2"},
    "date": {"mp4": "\xa9day", "mp3": "TDRC"},
    "genre": {"mp4": "\xa9gen", "mp3": "TCON"},
    "album": {"mp4": "\xa9alb", "mp3": "TALB"},
    "artist": {"mp4": "\xa9ART", "mp3": "TPE1"},
    "album_artist": {"mp4": "aART", "mp3": "TPE2"},
    "track": {"mp4": "trkn", "mp3": "TRCK"},
    "disk": {"mp4": "disk", "mp3": "TPOS"},
    "grouping": {"mp4": "\xa9grp", "mp3": "TIT1"},
    "album_sort_order": {"mp4": "soal", "mp3": "TSOA"},
    "track_sort_order": {"mp4": "sonm", "mp3": "TSOT"},
    "album_artist_sort_order": {"mp4": "soaa", "mp3": "TSO2"},
    "track_artist_sort_order": {"mp4": "soar", "mp3": "TSOP"},
}


class _NotSet:
    pass


def iter_categorized_music_files(paths):
    if isinstance(paths, str):
        paths = [paths]

    for path in paths:
        path = os.path.abspath(os.path.expanduser(path))
        if os.path.isdir(path):
            if path.endswith(("/", "\\")):
                path = path[:-1]
            for root, dirs, files in os.walk(path):
                if files and not dirs:
                    alb_root, alb_dir = os.path.split(root)
                    cat_root, cat_dir = os.path.split(alb_root)
                    art_root, art_dir = os.path.split(cat_root)
                    yield art_root, art_dir, cat_dir, alb_dir, _iter_music_files((os.path.join(root, f) for f in files))
        elif os.path.isfile(path):
            alb_root, alb_dir = os.path.split(os.path.dirname(path))
            cat_root, cat_dir = os.path.split(alb_root)
            art_root, art_dir = os.path.split(cat_root)
            yield art_root, art_dir, cat_dir, alb_dir, _iter_music_files(path)


def iter_music_albums(paths):
    if isinstance(paths, str):
        paths = [paths]

    for path in paths:
        path = os.path.abspath(os.path.expanduser(path))
        if os.path.isdir(path):
            if path.endswith(("/", "\\")):
                path = path[:-1]
            for root, dirs, files in os.walk(path):
                if files and not dirs:
                    alb_root, alb_dir = os.path.split(root)
                    yield alb_root, alb_dir, _iter_music_files((os.path.join(root, f) for f in files))
        elif os.path.isfile(path):
            alb_root, alb_dir = os.path.split(os.path.dirname(path))
            yield alb_root, alb_dir, _iter_music_files(path)


def iter_music_files(paths, include_backups=False):
    if isinstance(paths, str):
        paths = [paths]

    for path in paths:
        path = os.path.abspath(os.path.expanduser(path))
        if os.path.isdir(path):
            if path.endswith(("/", "\\")):
                path = path[:-1]
            for root, dirs, files in os.walk(path):
                yield from _iter_music_files((os.path.join(root, f) for f in files), include_backups)
        elif os.path.isfile(path):
            yield from _iter_music_files(path, include_backups)


def _iter_music_files(_path, include_backups=False):
    if isinstance(_path, str):
        _path = Path(_path).expanduser().resolve()
        paths = [p.as_posix() for p in _path.iterdir()] if _path.is_dir() else [_path.as_posix()]
    else:
        paths = _path

    for file_path in paths:
        music_file = SongFile(file_path)
        if music_file:
            yield music_file
        else:
            if include_backups and (os.path.splitext(file_path)[1][1:] not in NON_MUSIC_EXTS):
                found_backup = False
                for sha256sum, tags in load_tags(file_path).items():
                    found_backup = True
                    yield FakeMusicFile(sha256sum, tags)
                if not found_backup:
                    log.debug("Not a music file: {}".format(file_path))
            else:
                log.debug("Not a music file: {}".format(file_path))


def iter_album_dirs(paths):
    if isinstance(paths, str):
        paths = [paths]

    for _path in paths:
        path = Path(_path).expanduser().resolve()
        if path.is_dir():
            for root, dirs, files in os.walk(path.as_posix()):  # as_posix for 3.5 compatibility
                if files and not dirs:
                    yield AlbumDir(root)
        elif path.is_file():
            yield AlbumDir(path.parent)


class FakeMusicFile:
    def __init__(self, sha256sum, tags):
        self.filename = sha256sum
        self.tags = tags

    def tagless_sha256sum(self):
        return self.filename


class AlbumDir(ClearableCachedPropertyMixin):
    # __instances = WeakValueDictionary()

    # def __new__(cls, path):
    #     if not isinstance(path, Path):
    #         path = Path(path).expanduser().resolve()
    #
    #     try:
    #         return cls.__instances[path]
    #     except KeyError as e:
    #         obj = super().__new__(cls)
    #         if any(p.is_dir() for p in path.iterdir()):
    #             raise InvalidAlbumDir("Invalid album dir - contains directories: {}".format(path.as_posix()))
    #         cls.__instances[path] = obj
    #         return obj

    def __init__(self, path):
        """
        :param str|Path path: The path to a directory that contains one album's music files
        """
        # if not getattr(self, "_AlbumDir__initialized", False):
        if not isinstance(path, Path):
            path = Path(path).expanduser().resolve()
        if any(p.is_dir() for p in path.iterdir()):
            raise InvalidAlbumDir("Invalid album dir - contains directories: {}".format(path.as_posix()))
        self.path = path
            # self.__initialized = True

    def __repr__(self):
        try:
            rel_path = self.path.relative_to(Path(".").resolve()).as_posix()
        except Exception as e:
            rel_path = self.path.as_posix()
        return "<{}({!r})>".format(type(self).__name__, rel_path)

    def __iter__(self):
        yield from self.songs

    def move(self, dest_path):
        if not isinstance(dest_path, Path):
            dest_path = Path(dest_path)
        dest_path = dest_path.expanduser().resolve()

        if not dest_path.parent.exists():
            os.makedirs(dest_path.parent.as_posix())
        if dest_path.exists():
            raise ValueError("Destination for {} already exists: {!r}".format(self, dest_path.as_posix()))

        self.path.rename(dest_path)
        self.path = dest_path
        self.clear_cached_properties()

    @cached_property
    def songs(self):
        return list(_iter_music_files(self.path.as_posix()))

    @cached_property
    def name(self):
        album = self.path.name
        m = re.match("^\[\d{4}[0-9.]*\] (.*)$", album)  # Begins with date
        if m:
            album = m.group(1).strip()
        m = re.match("(.*)\s*\[.*Album\]", album)  # Ends with Xth Album
        if m:
            album = m.group(1).strip()
        return album

    @cached_property
    def artist_path(self):
        bad = (
            "album", "single", "soundtrack", "collaboration", "solo", "christmas", "download", "compilation",
            "unknown_fixme"
        )
        artist_path = self.path.parent
        lc_name = artist_path.name.lower()
        if not any(i in lc_name for i in bad):
            return artist_path

        artist_path = artist_path.parent
        lc_name = artist_path.name.lower()
        if not any(i in lc_name for i in bad):
            return artist_path
        log.error("Unable to determine artist path for {}".format(self))
        return None

    @cached_property
    def _type_path(self):
        """Not accurate if not already sorted"""
        return self.path.parent

    @property
    def length(self):
        """
        :return float: The length of this album in seconds
        """
        return sum(f.length for f in self.songs)

    @cached_property
    def length_str(self):
        """
        :return str: The length of this album in the format (HH:M)M:SS
        """
        length = format_duration(int(self.length))  # Most other programs seem to floor the seconds
        if length.startswith("00:"):
            length = length[3:]
        if length.startswith("0"):
            length = length[1:]
        return length

    @cached_property
    def wiki_artist(self):
        try:
            artists = {f.wiki_artist for f in self.songs if f.wiki_artist}
        except Exception as e:
            log.error("Error determining wiki_artist for one or more songs in {}: {}".format(self, e))
            return None

        if len(artists) == 1:
            return artists.pop()
        elif len(artists) > 1:
            log.warning("Conflicting wik_artist matches were found for {}: {}".format(self, ", ".join(map(str, artists))))
        else:
            # artist_path = self.artist_path
            # if artist_path is not None:
            #     try:
            #         return Artist(artist_path.name)
            #     except Exception as e:
            #         log.error("Error determining artist for {} based on path {}: {}".format(self, artist_path, e))
            # else:
            #     log.debug("No wiki_artist match was found for {}".format(self))
            log.debug("No wiki_artist match was found for {}".format(self))
        return None

    @cached_property
    def wiki_album(self):
        try:
            albums = {f.wiki_album for f in self.songs if f.wiki_album}
        except Exception as e:
            log.error("Error determining wiki_album for one or more songs in {}: {}".format(self, e))
            return None

        if len(albums) == 1:
            return albums.pop()
        elif len(albums) > 1:
            log.warning("Conflicting wiki_album matches were found for {}: {}".format(self, ", ".join(map(str, albums))))
        else:
            log.debug("No wiki_album match was found for {}".format(self))
        return None

    @cached_property
    def expected_rel_path(self):
        if self.wiki_album:
            return self.wiki_album.expected_rel_path
        elif self.wiki_artist:
            artist_dir = self.wiki_artist.expected_rel_path.name
            # artist_dir = self.wiki_artist.expected_dirname
            lc_name = self.path.name.lower()
            if any(val in lc_name for val in ("ost", "soundtrack", "part", "episode")):
                type_dir = "Soundtracks"
            else:
                type_dir = "UNKNOWN_FIXME"
            return os.path.join(artist_dir, type_dir, self.path.name)
        log.error("Unable to find an album or artist match for {}".format(self))
        return None

    def cleanup_partial_matches(self, dry_run):
        logged_messages = 0
        upd_prefix = "[DRY RUN] Would update" if dry_run else "Updating"
        rnm_prefix = "[DRY RUN] Would rename" if dry_run else "Renaming"
        cwd = Path(".").resolve()

        artist_dir = self.artist_path.name.lower() if self.artist_path else None
        if artist_dir:
            m = re.match(r"^{}\s*-?\s*(.*)$".format(artist_dir), self.path.name, re.IGNORECASE)
            if m:
                alb_dir = m.group(1).strip()
                if alb_dir and alb_dir != self.path.name:
                    new_alb_path = self.path.parent.joinpath(alb_dir)
                    try:
                        rel_path = new_alb_path.relative_to(cwd).as_posix()
                    except Exception as e:
                        rel_path = new_alb_path.as_posix()
                    logged_messages += 1
                    log.info("{} {} -> {}".format(rnm_prefix, self, rel_path))
                    if not dry_run:
                        self.move(new_alb_path)

        try:
            eng_dir, han_dir = split_name(self.name)
        except Exception as e:
            eng_dir, han_dir = None, None

        dests = {}
        conflicts = {}
        exists = set()
        for music_file in self.songs:
            to_update, orig, extras, eng, han = {}, {}, {}, {}, {}
            orig["file"] = filename_stripped = music_file.basename(True, True)
            orig["title"] = title = music_file.tag_text("title")
            orig["album"] = album = music_file.tag_text("album")

            new_filename = None
            with suppress(Exception):
                eng["file"], han["file"], extras["file"] = split_name(filename_stripped, extra=True)
                eng["title"], han["title"], extras["title"] = split_name(title, extra=True)
                eng["album"], han["album"], extras["album"] = split_name(album, extra=True)
                eng["dir"], han["dir"] = eng_dir, han_dir
                # log.info("{} => eng={}, han={}, extras={}".format(music_file, eng, han, extras), extra={"color": "magenta"})

                eng_vals = {val for val in eng.values() if val}
                han_vals = {val for val in han.values() if val}
                if all(len(lang_vals) == 1 for lang_vals in (eng_vals, han_vals)):
                    eng, han = eng_vals.pop(), han_vals.pop()
                    expected_base = "{} ({})".format(eng, han) if eng and han else eng or han
                    for field in ("file", "title", "album"):
                        expected = expected_base
                        if extras.get(field):
                            expected = "{} ({})".format(expected, extras[field])
                        if orig[field] != expected:
                            if field == "file":
                                new_filename = expected
                            else:
                                to_update[field] = (orig[field], expected)

            if artist_dir:
                for field in ("artist", "album_artist"):
                    original = music_file.tag_text(field)
                    artists = []
                    try:
                        eng, han = split_name(original)
                    except Exception as e:
                        if "," in original:
                            with suppress(Exception):
                                for orig in map(str.strip, original.split(",")):
                                    e, h = split_name(orig)
                                    if any("&" in lang for lang in (e, h)) and not all("&" in lang for lang in (e, h)):
                                        artists.append(orig)
                                    else:
                                        artists.append("{} ({})".format(e, h) if e and h else e or h)
                    else:
                        artists.append("{} ({})".format(eng, han) if eng and han else eng or han)

                    if len(artists) == 1 and self.wiki_artist:
                        file_artist = artists[0]
                        wiki_artist_name = self.wiki_artist.name_with_context
                        if wiki_artist_name.lower() == file_artist.lower():
                            new_artist = wiki_artist_name
                        else:
                            new_artist = file_artist

                        if original != new_artist:
                            to_update[field] = (original, new_artist)
                    elif artists:
                        artists = sorted(artists)
                        primary = None
                        for artist in artists:
                            if artist.lower().startswith(artist_dir):
                                primary = artist
                                break
                        if primary:
                            artists.remove(primary)
                            artists.insert(0, primary)

                        artist_str = ", ".join(artists)
                        if original != artist_str:
                            to_update[field] = (original, artist_str)

            file_genre = music_file.tag_text("genre", default=None)
            if any(contains_hangul(music_file.tag_text(f)) for f in ("title", "album")) and file_genre != "K-pop":
                to_update["genre"] = (file_genre, "K-pop")

            if to_update:
                logged_messages += 1
                msg = "{} {} by changing...".format(upd_prefix, music_file)
                for tag, (old_val, new_val) in sorted(to_update.items()):
                    msg += "\n   - {} from {!r} to {!r}".format(tag, old_val, new_val)
                log.info(msg)
                if not dry_run:
                    try:
                        for tag, (old_val, new_val) in sorted(to_update.items()):
                            music_file.set_text_tag(tag, new_val, by_id=False)
                    except TagException as e:
                        log.error(e)
                    else:
                        music_file.save()
            else:
                log.log(19, "No tag changes necessary for {}".format(music_file.extended_repr))

            if new_filename:
                final_filename = "{}.{}".format(new_filename, music_file.ext)
                track = music_file.tag_text("track")
                if track:
                    final_filename = "{:02d}. {}".format(int(track), final_filename)

                if music_file.path.name != final_filename:
                    dest_path = music_file.path.parent.joinpath(final_filename)
                    if dest_path.exists():
                        if not music_file.path.samefile(dest_path):
                            logged_messages += 1
                            log.warning("File already exists at destination for {}: {!r}".format(music_file, dest_path.as_posix()), extra={"color": "yellow"})
                            exists.add(dest_path)
                        else:
                            log.log(19, "File already has the correct path: {}".format(music_file))
                            continue

                    if dest_path in dests:
                        logged_messages += 1
                        log.warning("Duplicate destination conflict for {}: {!r}".format(music_file, dest_path.as_posix()), extra={"color": "yellow"})
                        conflicts[music_file] = dest_path
                        conflicts[dests[dest_path]] = dest_path
                    else:
                        dests[dest_path] = music_file

        if exists:
            raise RuntimeError("Files already exist in {:,d} destinations for {} songs".format(len(exists), self))
        elif conflicts:
            raise RuntimeError("There are {:,d} duplicate destination conflicts for {} songs".format(len(conflicts), self))

        for dest_path, music_file in sorted(dests.items()):
            logged_messages += 1
            try:
                rel_path = dest_path.relative_to(cwd).as_posix()
            except Exception as e:
                rel_path = dest_path.as_posix()
            log.info("{} {!r} -> {!r}".format(rnm_prefix, music_file.rel_path, rel_path))
            if not dry_run:
                music_file.rename(dest_path)

        if not dests and not logged_messages:
            log.log(19, "No changes necessary for {}".format(self))
        return logged_messages

    def update_song_tags_and_names(self, allow_incomplete, dry_run):
        logged_messages = 0
        if not self.wiki_artist:
            log.error("Unable to find wiki artist match for {} - skipping tag updates".format(self), extra={"red": True})
            return 1
        elif not self.wiki_album:
            if allow_incomplete:
                logged_messages += 1
                log.warning("Unable to find wiki album match for {} - will only consider updating artist tag".format(self), extra={"color": "red"})
            else:
                log.error("Unable to find wiki album match for {} - skipping tag updates".format(self), extra={"red": True})
                return 1

        updatable = [
            ("title", "file_title"), ("artist", "name_with_context"), ("album_artist", "name_with_context"),
            ("album", "name")
        ]
        upd_prefix = "[DRY RUN] Would update" if dry_run else "Updating"
        rnm_prefix = "[DRY RUN] Would rename" if dry_run else "Renaming"
        cwd = Path(".").resolve()

        genre = None
        if self.wiki_album and (self.wiki_album.language in ("Korean", "Japanese", "Chinese")):
            genre = "{}-pop".format(self.wiki_album.language[0])

        dests = {}
        conflicts = {}
        exists = set()
        for music_file in self.songs:
            to_update = {}
            wiki_song = music_file.wiki_song
            if wiki_song is None:
                logged_messages += 1
                log.error("Unable to find wiki song match for {}".format(music_file), extra={"red": True})
                if not allow_incomplete:
                    continue

                file_value = music_file.tag_text("artist")
                wiki_artist = music_file.wiki_artist
                if wiki_artist:
                    # wiki_value = wiki_artist.name_with_context
                    try:
                        member_of = wiki_artist.member_of
                    except AttributeError:
                        wiki_value = wiki_artist.name
                    else:
                        wiki_value = '{} [{}]'.format(wiki_artist.name, member_of.name)

                    if (file_value != wiki_value) and (file_value.count(",") == wiki_value.count(",")):
                        to_update["artist"] = (file_value, wiki_value)
            else:
                for field, attr in updatable:
                    file_value = music_file.tag_text(field, default=None)
                    wiki_field = "artist" if field == "album_artist" else field
                    wiki_value = getattr(wiki_song if field == "title" else getattr(wiki_song, wiki_field), attr)
                    if file_value != wiki_value:
                        to_update[field] = (file_value, wiki_value)

                file_genre = music_file.tag_text("genre")
                if genre and file_genre != genre:
                    to_update["genre"] = (file_genre, genre)

            if to_update:
                logged_messages += 1
                msg = "{} {} to match {} by changing...".format(upd_prefix, music_file, wiki_song)
                for tag, (old_val, new_val) in sorted(to_update.items()):
                    msg += "\n   - {} from {!r} to {!r}".format(tag, old_val, new_val)
                log.info(msg)
                if not dry_run:
                    try:
                        for tag, (old_val, new_val) in sorted(to_update.items()):
                            music_file.set_text_tag(tag, new_val, by_id=False)
                    except TagException as e:
                        log.error(e)
                    else:
                        music_file.save()
            else:
                log.log(19, "No tag changes necessary for {} == {}".format(music_file.extended_repr, wiki_song))

            if wiki_song is None:
                continue

            expected_filename = wiki_song.expected_filename(music_file.ext)
            current_filename = music_file.path.name
            if (expected_filename != current_filename) and not current_filename.endswith(expected_filename):
                dest_path = music_file.path.parent.joinpath(expected_filename)
                if dest_path.exists():
                    if not music_file.path.samefile(dest_path):
                        logged_messages += 1
                        log.warning("File already exists at destination for {}: {!r}".format(music_file, dest_path.as_posix()), extra={"color": "yellow"})
                        exists.add(dest_path)
                    else:
                        log.log(19, "File already has the correct path: {}".format(music_file))
                        continue

                if dest_path in dests:
                    logged_messages += 1
                    log.warning("Duplicate destination conflict for {}: {!r}".format(music_file, dest_path.as_posix()), extra={"color": "yellow"})
                    conflicts[music_file] = dest_path
                    conflicts[dests[dest_path]] = dest_path
                else:
                    dests[dest_path] = music_file

        if exists:
            raise RuntimeError("Files already exist in {:,d} destinations for {} songs".format(len(exists), self))
        elif conflicts:
            raise RuntimeError("There are {:,d} duplicate destination conflicts for {} songs".format(len(conflicts), self))

        for dest_path, music_file in sorted(dests.items()):
            logged_messages += 1
            try:
                rel_path = dest_path.relative_to(cwd).as_posix()
            except Exception as e:
                rel_path = dest_path.as_posix()
            log.info("{} {!r} -> {!r}".format(rnm_prefix, music_file.rel_path, rel_path))
            if not dry_run:
                music_file.rename(dest_path)

        if not dests and not logged_messages:
            log.log(19, "No changes necessary for {}".format(self))
        return logged_messages

    def fix_song_tags(self, dry_run):
        prefix, add_msg, rmv_msg = ("[DRY RUN] ", "Would add", "remove") if dry_run else ("", "Adding", "removing")
        upd_msg = "Would update" if dry_run else "Updating"

        for music_file in self.songs:
            if music_file.ext != "mp3":
                log.debug("Skipping non-MP3: {}".format(music_file))
                continue

            tdrc = music_file.tags.getall("TDRC")
            txxx_date = music_file.tags.getall("TXXX:DATE")
            if (not tdrc) and txxx_date:
                file_date = txxx_date[0].text[0]

                log.info("{}{} TDRC={} to {} and {} its TXXX:DATE tag".format(
                    prefix, add_msg, file_date, music_file, rmv_msg
                ))
                if not dry_run:
                    music_file.tags.add(TDRC(text=file_date))
                    music_file.tags.delall("TXXX:DATE")
                    music_file.save()

            changes = 0
            for uslt in music_file.tags.getall("USLT"):
                m = re.match("^(.*)(https?://\S+)$", uslt.text, re.DOTALL)
                if m:
                    # noinspection PyUnresolvedReferences
                    new_lyrics = m.group(1).strip() + "\r\n"
                    log.info("{}{} lyrics for {} from {!r} to {!r}".format(
                        prefix, upd_msg, music_file, tag_repr(uslt.text), tag_repr(new_lyrics)
                    ))
                    if not dry_run:
                        uslt.text = new_lyrics
                        changes += 1

            if changes and not dry_run:
                log.info("Saving changes to lyrics in {}".format(music_file))
                music_file.save()

    def remove_bad_tags(self, dry_run):
        prefix = "[DRY RUN] Would remove" if dry_run else "Removing"
        i = 0
        for music_file in self.songs:
            if isinstance(music_file.tags, MP4Tags):
                tag_id_pats = RM_TAGS_MP4
            elif isinstance(music_file.tags, ID3):
                tag_id_pats = RM_TAGS_ID3
            else:
                raise TypeError("Unhandled tag type: {}".format(type(music_file.tags).__name__))

            to_remove = {}
            for tag, val in sorted(music_file.tags.items()):
                if any(fnmatch(tag, pat) for pat in tag_id_pats):
                    to_remove[tag] = val if isinstance(val, list) else [val]

            if to_remove:
                if i:
                    log.debug("")
                rm_str = ", ".join(
                    "{}: {}".format(tag_id, tag_repr(val)) for tag_id, vals in sorted(to_remove.items()) for val in vals
                )
                info_str = ", ".join("{} ({})".format(tag_id, len(vals)) for tag_id, vals in sorted(to_remove.items()))

                log.info("{} tags from {}: {}".format(prefix, music_file, info_str))
                log.debug("\t{}: {}".format(music_file.filename, rm_str))
                if not dry_run:
                    for tag_id in to_remove:
                        if isinstance(music_file.tags, MP4Tags):
                            del music_file.tags[tag_id]
                        elif isinstance(music_file.tags, ID3):
                            music_file.tags.delall(tag_id)
                    music_file.save()
                i += 1
            else:
                log.debug("{}: Did not have the tags specified for removal".format(music_file.filename))

        if not i:
            log.debug("None of the songs in {} had any tags that needed to be removed".format(self))


class SongFile(ClearableCachedPropertyMixin):
    """Adds some properties/methods to mutagen.File types that facilitate other functions"""
    def __new__(cls, file_path, *args, **kwargs):
        file_path = Path(file_path).expanduser().as_posix()
        try:
            music_file = mutagen.File(file_path, *args, **kwargs)
        except Exception as e:
            log.debug("Error loading {}: {}".format(file_path, e))
            music_file = None

        if music_file:
            obj = super().__new__(cls)
            obj._f = music_file
            return obj
        else:
            return None

    def __init__(self, file_path, *args, **kwargs):
        if not getattr(self, "_SongFile__initialized", False):
            self.wiki_scores = {}
            self.__initialized = True

    def __getattr__(self, item):
        return getattr(self._f, item)

    def __getitem__(self, item):
        return self._f[item]

    def __repr__(self):
        # ftype = "[{}]".format(self.ext) if self.ext is not None else ""
        return "<{}({!r})>".format(type(self).__name__, self.rel_path)

    @classmethod
    def for_plex_track(cls, track, root=None):
        if root is None:
            root_path_file = Path('~/.plex/server_path_root.txt').expanduser().resolve()
            if root_path_file.exists():
                root = root_path_file.open('r').read().strip()
            if not root:
                raise ValueError('A server root path must be provided or be in {}'.format(root_path_file.as_posix()))

        return cls(Path(root).joinpath(track.media[0].parts[0].file).resolve())

    @cached_property
    def extended_repr(self):
        try:
            info = "[{!r} by {}, in {!r}]".format(self.tag_title, self.tag_artist, self.album_name_cleaned)
        except Exception as e:
            info = ""
        return "<{}({!r}){}>".format(type(self).__name__, self.rel_path, info)

    @property
    def rel_path(self):
        try:
            return self.path.relative_to(Path(".").resolve()).as_posix()
        except Exception as e:
            return self.path.as_posix()

    def rename(self, dest_path):
        if not isinstance(dest_path, Path):
            dest_path = Path(dest_path).expanduser().resolve()

        if not dest_path.parent.exists():
            os.makedirs(dest_path.parent.as_posix())
        if dest_path.exists():
            raise ValueError("Destination for {} already exists: {!r}".format(self, dest_path.as_posix()))

        self.path.rename(dest_path)
        self.clear_cached_properties()
        # noinspection PyAttributeOutsideInit
        self._f = mutagen.File(dest_path.as_posix())

    def save(self):
        self.tags.save(self._f.filename)

    @cached_property
    def path(self):
        return Path(self._f.filename).resolve()

    @property
    def rating(self):
        """The rating for this track on a scale of 1-255"""
        if isinstance(self.tags, MP4Tags):
            try:
                return self.tags['POPM'][0]
            except KeyError:
                return None
        else:
            try:
                return self.get_tag('POPM', True).rating
            except TagNotFound:
                return None

    @rating.setter
    def rating(self, value):
        if isinstance(self.tags, MP4Tags):
            self.tags['POPM'] = [value]
        else:
            try:
                tag = self.get_tag('POPM', True)
            except TagNotFound:
                self.tags.add(POPM(rating=value))
            else:
                tag.rating = value
        self.save()

    @property
    def star_rating_10(self):
        star_rating_5 = self.star_rating
        if star_rating_5 is None:
            return None
        star_rating_10 = star_rating_5 * 2
        a, b, c = RATING_RANGES[star_rating_5 - 1]
        # log.debug('rating = {}, stars/5 = {}, a={}, b={}, c={}'.format(self.rating, star_rating_5, a, b, c))
        if star_rating_5 == 1 and self.rating < c:
            return 1
        return star_rating_10 + 1 if self.rating > c else star_rating_10

    @star_rating_10.setter
    def star_rating_10(self, value):
        if not isinstance(value, (int, float)) or not 0 < value < 11:
            raise ValueError('Star ratings must be ints on a scale of 1-10; invalid value: {}'.format(value))
        elif value == 1:
            self.rating = 1
        else:
            base, extra = divmod(int(value), 2)
            self.rating = RATING_RANGES[base - 1][2] + extra

    @property
    def star_rating(self):
        """
        This implementation uses the ranges specified here: https://en.wikipedia.org/wiki/ID3#ID3v2_rating_tag_issue

        :return int|None: The star rating equivalent of this track's POPM rating
        """
        rating = self.rating
        if rating is not None:
            for stars, (a, b, c) in enumerate(RATING_RANGES):
                if a <= rating <= b:
                    return stars + 1
        return None

    @star_rating.setter
    def star_rating(self, value):
        """
        This implementation uses the same values specified in the following link, except for 1 star, which uses 15
        instead of 1: https://en.wikipedia.org/wiki/ID3#ID3v2_rating_tag_issue

        :param int value: The number of stars to set
        :return:
        """
        if not isinstance(value, (int, float)) or not 0 < value < 5.5:
            raise ValueError('Star ratings must on a scale of 1-5; invalid value: {}'.format(value))
        elif int(value) != value:
            if int(value) + 0.5 == value:
                self.star_rating_10 = int(value * 2)
            else:
                raise ValueError('Star ratings must be a multiple of 0.5; invalid value: {}'.format(value))
        else:
            self.rating = RATING_RANGES[int(value) - 1][2]

    @property
    def length(self):
        """
        :return float: The length of this song in seconds
        """
        return self._f.info.length

    @cached_property
    def length_str(self):
        """
        :return str: The length of this song in the format (HH:M)M:SS
        """
        length = format_duration(int(self._f.info.length))  # Most other programs seem to floor the seconds
        if length.startswith("00:"):
            length = length[3:]
        if length.startswith("0"):
            length = length[1:]
        return length

    @cached_property
    def album_name_cleaned(self):
        album = self.tag_text("album")
        m = re.match("(.*)\s*\[.*Album\]", album)
        if m:
            album = m.group(1).strip()

        m = re.match("^(.*?)\s*(?:the)?\s*[0-9](?:st|nd|rd|th)\s+\S*\s*album\s*(?:repackage)?\s*(.*)$", album, re.I)
        if m:
            album = " ".join(map(str.strip, m.groups())).strip()

        m = re.search(r'((?:^|\s+)\d+\s*집(?:$|\s+))', album)   # {num}집 == nth album
        if m:
            album = album.replace(m.group(1), ' ').strip()

        # m = re.search("(?:the)?\s*[0-9](?:st|nd|rd|th)\s+\S*\s*album(.*)$", album, re.IGNORECASE)
        # if m:
        #     group = m.group(1).strip()
        #     if group:
        #         album = group
        #
        # m = re.match("^(.*?)\s*[-:] (?:the)?\s*[0-9](?:st|nd|rd|th)\s+\S*\s*album\s*(?:repackage)?$", album, re.IGNORECASE)
        # if m:
        #     group = m.group(1).strip()
        #     if group:
        #         album = group

        return album

    @cached_property
    def album_from_dir(self):
        album = self.path.parent.name
        m = re.match("^\[\d{4}[0-9.]*\] (.*)$", album)   # Begins with date
        if m:
            album = m.group(1).strip()
        m = re.match("(.*)\s*\[.*Album\]", album)       # Ends with Xth Album
        if m:
            album = m.group(1).strip()
        return album

    @cached_property
    def tag_title(self):
        return self.tag_text("title")

    def set_title(self, title):
        self.set_text_tag("title", title, by_id=False)

    @cached_property
    def tag_artist(self):
        return self.tag_text("artist")

    @cached_property
    def in_competition_album(self):
        try:
            album_artist = self.tag_text('album_artist')
        except Exception:
            return False
        else:
            if album_artist.lower().startswith('produce'):
                if album_artist.split()[-1].isdigit():
                    return True
        return False

    @cached_property
    def track_num(self):
        track = self.tag_text("track", default=None)
        if track:
            if "/" in track:
                track = track.split("/")[0].strip()
            if "," in track:
                track = track.split(",")[0].strip()
            if track.startswith("("):
                track = track[1:].strip()
        return track

    @cached_property
    def wiki_artist(self):
        artists = split_names(self.tag_artist)
        exc = None
        for eng, cjk, of_group in artists:
            if self.in_competition_album:
                return WikiArtist(name=eng or cjk, no_fetch=True)
            try:
                return WikiArtist(of_group=of_group, aliases=tuple(filter(None, (eng, cjk))))
            except WikiEntityIdentificationException as e:
                log.error('Error matching artist {} for {}: {}'.format((eng, cjk, of_group), self, e))
            except CodeBasedRestException as e:
                exc = e
            except AttributeError as e:
                log.error('Error matching artist {} for {}: {}'.format((eng, cjk, of_group), self, e))
                traceback.print_exc()
            except Exception as e:
                log.error('Error matching artist {} for {}: {}'.format((eng, cjk, of_group), self, e))
                if len(artists) > 1:
                    log.info('{} has additional artists: {}'.format(self, artists))
                raise e
        if exc:
            log.error('Error matching artist {} for {}: {}'.format(artists, self, exc))
            raise exc

    @cached_property
    def wiki_album(self):
        self.wiki_scores["album"] = -1
        try:
            artist = self.wiki_artist
        except Exception as e:
            log.error('Error determining artist for {}: {}'.format(self, e))
            traceback.print_exc()
            raise e
        else:
            try:
                album, score = artist.find_song_collection(self.album_name_cleaned, include_score=True)
            except Exception as e:
                log.error('Error determining album for {} from {}: {}'.format(self, artist, e))
                traceback.print_exc()
                raise e
            self.wiki_scores["album"] = score
            if album is None:
                fmt = 'Unable to find album {!r} from {} to match {}'
                log.warning(fmt.format(self.album_name_cleaned, artist, self), extra={'color': 9})
            return album

    @cached_property
    def wiki_song(self):
        self.wiki_scores["song"] = -1
        name = self.tag_title
        num = self.track_num
        try:
            album = self.wiki_album
        except Exception as e:
            log.error('Error determining album for {}: {}'.format(self, e))
            traceback.print_exc()
            raise e
        else:
            if not album:
                return None
            try:
                track, score = album.find_track(name, track=num, include_score=True)
            except Exception as e:
                log.error('Error determining track for {} from {}: {}'.format(self, album, e))
                traceback.print_exc()
                raise e
            else:
                self.wiki_scores["song"] = score
                return track

    @cached_property
    def wiki_artist_old(self):
        eng, han = None, None
        try:
            eng, han = split_name(self.tag_artist, is_artist=True)
        except ValueError as e:
            ap = self._artist_path
            if ap and "," in self.tag_artist:
                try:
                    artists = map(split_name, map(str.strip, self.tag_artist.split(",")))
                except Exception as e1:
                    pass
                else:
                    lc_artist_dir = ap.name.lower()
                    for _eng, _han in artists:
                        if _eng.lower() in lc_artist_dir:
                            eng, han = _eng, _han
                            log.warning("Using artist {!r} instead of {!r} for {}".format(eng, self.tag_artist, self), extra={"color": "cyan"})
                            break
            if not eng:
                log.error("Error splitting into eng+han: {!r} [for {}]".format(self.tag_artist, self))
                return None
        else:
            if not eng:
                return None

        lc_eng = eng.lower()
        collab_indicators = ("and", "&", "feat", ",")
        if any(i in lc_eng for i in collab_indicators):
            for lc_artist in sorted(Artist.known_artist_names()):
                if lc_artist in lc_eng:
                    log.warning("Using artist {!r} instead of {!r} for {}".format(lc_artist, eng, self), extra={"color": "cyan"})
                    return Artist(lc_artist)

        try:
            return Artist(eng)
        except CodeBasedRestException as e:
            m = re.match("^(.*?)\s*\((.*)\)$", eng)
            if m:
                name = m.group(1).strip().lower()
                group_name = m.group(2).strip()
                try:
                    group = Artist(group_name)
                except CodeBasedRestException as e2:
                    log.error("Error retrieving information from wiki about artist {!r} for {}: {}".format(group_name, self, e))
                else:
                    for member in group.members:
                        if isinstance(member, Artist) and member.english_name.lower() == name:
                            return member

            log.error("Error retrieving information from wiki about artist {!r} for {}: {}".format(eng, self, e))
            return None
        except Exception as e:
            log.error("Error processing {}: {}\n{}".format(self, e, traceback.format_exc()))
            return None

    @cached_property
    def wiki_album_old(self):
        self.wiki_scores["album"] = -1
        try:
            artist = self.wiki_artist
            album, score = artist._find_album(self.album_name_cleaned) if artist else (None, -1)
            if album:
                if score < 100:
                    song, song_score = artist._find_song(self.tag_title, album=album)
                    if not song:
                        log.debug("{} was a match for album {} with score {}, but the song title did not match a song in that album".format(self, album, score))
                    else:
                        self.wiki_scores["album"] = score
                        return album
                else:
                    self.wiki_scores["album"] = score
                    return album

            if artist:
                song, song_score = artist._find_song(self.tag_title)
                if song:
                    try:
                        album_score = fuzz.token_sort_ratio(song.album.title, self.album_name_cleaned, force_ascii=False)
                    except AttributeError as e:
                        pass                        # If it was a CollaborationSong
                    else:
                        if album_score < 60:
                            log.debug("{} was a match for song {} with score {}, but the album title did not match closely enough ({})".format(self, song, song_score, album_score))
                            return None

                    self.__dict__["wiki_song"] = song
                    self.wiki_scores["song"] = song_score
                    try:
                        album = song.album
                    except AttributeError as e:
                        return None                 # It's a CollaborationSong
                    log.debug("Matched {} to {} via song".format(self, album))
                    return album

            msg = "Unable to match album {!r} for {}".format(self.album_name_cleaned, self)
            lc_name = self.album_name_cleaned.lower()
            if any(val in lc_name for val in ("ost", "soundtrack", "part", "episode")):
                log.debug(msg)
            else:
                log.warning(msg)
            return None
        except Exception as e:
            log.error("Encountered {} while trying to find wiki album for {}: {}\n{}".format(type(e).__name__, self, e, traceback.format_exc()))
            raise e

    @cached_property
    def wiki_song_old(self):
        self.wiki_scores["song"] = -1
        artist = self.wiki_artist
        # noinspection PyTypeChecker
        track = self.tag_text("track", default=None)
        if track:
            if "/" in track:
                track = track.split("/")[0].strip()
            if "," in track:
                track = track.split(",")[0].strip()
            if track.startswith("("):
                track = track[1:].strip()
        try:
            song, score = artist._find_song(self.tag_title, album=self.wiki_album, track=track) if artist else (None, -1)
        except Exception as e:
            log.error("Encountered {} while processing {}: {}".format(type(e).__name__, self, e))
            raise e
        else:
            if song and not self.wiki_album and not isinstance(song, CollaborationSong):
                fmt = "Song {} on album {} was closest to {}, but it is not a CollaborationSong, and no album-level match was found"
                log.debug(fmt.format(song, song.album, self))
                return None

            self.wiki_scores["song"] = score
            return song

    @cached_property
    def wiki_expected_rel_path(self):
        ext = self.ext
        if self.wiki_song:
            return self.wiki_song.expected_rel_path(ext)
        elif self.wiki_album:
            return os.path.join(self.wiki_album.expected_rel_path, self.basename())
        elif self.wiki_artist and ("single" in self.album_type_dir.lower()):
            artist_dir = self.wiki_artist.expected_rel_path.name
            # artist_dir = self.wiki_artist.expected_dirname
            dest = os.path.join(artist_dir, self.path.parents[1].name, self.path.parent.name, self.basename())
            log.warning("{}.wiki_expected_rel_path defaulting to {!r}".format(self, dest))
            return dest
        return None

    @cached_property
    def _artist_path(self):
        bad = (
            "album", "single", "soundtrack", "collaboration", "solo", "christmas", "download", "compilation",
            "unknown_fixme"
        )
        artist_path = self.path.parents[1]
        lc_name = artist_path.name.lower()
        if not any(i in lc_name for i in bad):
            return artist_path

        artist_path = artist_path.parent
        lc_name = artist_path.name.lower()
        if not any(i in lc_name for i in bad):
            return artist_path
        log.error("Unable to determine artist path for {}".format(self))
        return None

    @cached_property
    def album_type_dir(self):
        return self.path.parents[1].name

    @cached_property
    def ext(self):
        if isinstance(self.tags, MP4Tags):
            return self.path.suffix[1:]
        elif isinstance(self.tags, ID3):
            return "mp3"
        return None

    @cached_property
    def _tag_type(self):
        if isinstance(self.tags, MP4Tags):
            return "mp4"
        elif isinstance(self.tags, ID3):
            return "mp3"
        return None

    def basename(self, no_ext=False, trim_prefix=False):
        basename = self.path.stem if no_ext else self.path.name
        if trim_prefix:
            m = re.match(r"\d+\.?\s*(.*)", basename)
            if m:
                basename = m.group(1)
        return basename

    def set_text_tag(self, tag, value, by_id=False):
        tag_id = tag if by_id else self.tag_name_to_id(tag)
        if isinstance(self.tags, MP4Tags):
            self.tags[tag_id] = value
        elif self.ext == "mp3":
            try:
                tag_cls = getattr(mutagen.id3._frames, tag_id.upper())
            except AttributeError as e:
                raise ValueError("Invalid tag for {}: {} (no frame class found for it)".format(self, tag)) from e
            else:
                self.tags[tag_id] = tag_cls(text=value)
        else:
            raise TypeError("Unable to set {!r} for {} because its extension is {!r}".format(tag, self, self.ext))

    def tag_name_to_id(self, tag_name):
        """
        :param str tag_name: The file type-agnostic name of a tag, e.g., 'title' or 'date'
        :return str: The tag ID appropriate for this file based on whether it is an MP3 or MP4
        """
        try:
            type2id = TYPED_TAG_MAP[tag_name]
        except KeyError as e:
            raise InvalidTagName(tag_name, self) from e
        try:
            return type2id[self._tag_type]
        except KeyError as e:
            raise UnsupportedTagForFileType(tag_name, self) from e

    def tags_for_id(self, tag_id):
        """
        :param str tag_id: A tag ID
        :return list: All tags from this file with the given ID
        """
        if self.ext == "mp3":
            return self.tags.getall(tag_id.upper())         # all MP3 tags are uppercase; some MP4 tags are mixed case
        return self.tags.get(tag_id, [])                    # MP4Tags doesn't have getall() and always returns a list

    def tags_named(self, tag_name):
        """
        :param str tag_name: A tag name; see :meth:`.tag_name_to_id` for mapping of names to IDs
        :return list: All tags from this file with the given name
        """
        return self.tags_for_id(self.tag_name_to_id(tag_name))

    def get_tag(self, tag, by_id=False):
        """
        :param str tag: The name of the tag to retrieve, or the tag ID if by_id is set to True
        :param bool by_id: The provided value was a tag ID rather than a tag name
        :return: The tag object if there was a single instance of the tag with the given name/ID
        :raises: :class:`TagValueException` if multiple tags were found with the given name/ID
        :raises: :class:`TagNotFound` if no tags were found with the given name/ID
        """
        tags = self.tags_for_id(tag) if by_id else self.tags_named(tag)
        if len(tags) > 1:
            fmt = "Multiple {!r} tags found for {}: {}"
            raise TagValueException(fmt.format(tag, self, ", ".join(map(repr, tags))))
        elif not tags:
            raise TagNotFound("No {!r} tags were found for {}".format(tag, self))
        return tags[0]

    def tag_text(self, tag, strip=True, by_id=False, default=_NotSet):
        """
        :param str tag: The name of the tag to retrieve, or the tag ID if by_id is set to True
        :param bool strip: Strip leading/trailing spaces from the value before returning it
        :param bool by_id: The provided value was a tag ID rather than a tag name
        :param None|Str default: Default value to return when a TagValueException would otherwise be raised
        :return str: The text content of the tag with the given name if there was a single value
        :raises: :class:`TagValueException` if multiple values existed for the given tag
        """
        try:
            _tag = self.get_tag(tag, by_id)
        except TagNotFound as e:
            if default is not _NotSet:
                return default
            raise e
        vals = getattr(_tag, "text", _tag)
        if not isinstance(vals, list):
            vals = [vals]
        vals = list(map(str, vals))
        if len(vals) > 1:
            msg = "Multiple {!r} values found for {}: {}".format(tag, self, ", ".join(map(repr, vals)))
            if default is not _NotSet:
                log.warning(msg)
                return default
            raise TagValueException(msg)
        elif not vals:
            if default is not _NotSet:
                return default
            raise TagValueException("No {!r} tag values were found for {}".format(tag, self))
        return vals[0].strip() if strip else vals[0]

    def all_tag_text(self, tag_name, suppress_exc=True):
        try:
            for tag in self.tags_named(tag_name):
                yield from tag
        except KeyError as e:
            if suppress_exc:
                log.debug("{} has no {} tags - {}".format(self, tag_name, e))
            else:
                raise e

    def tagless_sha256sum(self):
        with self.path.open('rb') as f:
            tmp = BytesIO(f.read())

        try:
            mutagen.File(tmp).tags.delete(tmp)
        except AttributeError as e:
            log.error("Error determining tagless sha256sum for {}: {}".format(self.filename, e))
            return self.filename

        tmp.seek(0)
        return sha256(tmp.read()).hexdigest()

    def sha256sum(self):
        with self.path.open('rb') as f:
            return sha256(f.read()).hexdigest()

    # @cached_property
    # def acoustid_fingerprint(self):
    #     """Returns the 2-tuple of this file's (duration, fingerprint)"""
    #     return acoustid.fingerprint_file(self.filename)


def load_tags(paths):
    if isinstance(paths, str):
        paths = [paths]

    tag_info = {}
    for path in paths:
        if os.path.isdir(path):
            for root, dirs, files in os.walk(path):     # dirs can be ignored because walk will step through them -
                for f in files:                         #  they will be part of root on subsequent iterations
                    _load_tags(tag_info, os.path.join(root, f))
        elif os.path.isfile(path):
            _load_tags(tag_info, path)
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


def _load_tags(tag_info, file_path):
    try:
        music_file = SongFile(file_path)
    except Exception as e:
        log.debug("Error loading {}: {}".format(file_path, e))
        music_file = None

    if music_file:
        content_hash = music_file.tagless_sha256sum()
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


# class AcoustidDB:
#     lookup_meta = "recordings releasegroups"
#
#     def __init__(self, apikey=None, keyfile="~/acoustid_apikey.txt"):
#         if apikey is None:
#             keyfile_path = os.path.expanduser(keyfile)
#             try:
#                 with open(keyfile_path, "r") as keyfile:
#                     apikey = keyfile.read()
#             except OSError as e:
#                 raise ValueError("An API key is required; unable to find or read {}".format(keyfile_path))
#         self.apikey = apikey
#         self._cache = DBCache("acoustid", cache_subdir="acoustid", preserve_old=True)
#
#     @cached("_cache", lock=True, key=CacheKey.simple_noself)
#     def _lookup(self, duration, fingerprint, meta=None):
#         return acoustid.lookup(self.apikey, fingerprint, duration, meta or self.lookup_meta)
#
#     def lookup(self, emf):
#         results = self._lookup(*emf.acoustid_fingerprint)#["results"]
#
#         return results
#
#         # best = max(results, key=itemgetter("score"))
#         #
#         # return best
#
#         # best_ids = [rec["id"] for rec in best["recordings"]]
#         # if len(best_ids) > 1:
#         #     logging.warning("Found multiple recordings in best result with score {}: {}".format(best["score"], ", ".join(best_ids)))
#         #
#         # return self.get_track(best_ids[0])


class TagException(Exception):
    """Generic exception related to problems with tags"""


class TagNotFound(TagException):
    """Exception to be raised when a given tag cannot be found"""


class TagAccessException(TagException):
    """Exception to be raised when unable to access a given tag"""
    def __init__(self, tag, file_obj):
        self.tag = tag
        self.obj = file_obj


class UnsupportedTagForFileType(TagAccessException):
    """Exception to be raised when attempting to access a tag on an unsupported file type"""
    def __repr__(self):
        fmt = "Accessing/modifying {!r} tags is not supported on {} because it is a {!r} file"
        return fmt.format(self.tag, self.obj, self.obj.ext)


class InvalidTagName(TagAccessException):
    """Exception to be raised when attempting to retrieve the value for a tag that does not exist"""
    def __repr__(self):
        return "Invalid tag name {!r} for file {}".format(self.tag, self.obj)


class TagValueException(TagException):
    """Exception to be raised when a tag with an unexpected value is encountered"""


class WikiMatchException(Exception):
    """Exception to be raised when unable to find a match for a given field in the wiki"""


class InvalidAlbumDir(Exception):
    """Exception to be raised when an AlbumDir is initialized with an invalid directory"""


if __name__ == "__main__":
    from .patches import apply_mutagen_patches
    apply_mutagen_patches()
