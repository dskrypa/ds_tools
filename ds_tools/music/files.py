#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
:author: Doug Skrypa
"""

import logging
import os
import pickle
import re
import string
import traceback
from hashlib import sha256
from io import BytesIO
from pathlib import Path

# import acoustid
import mutagen
import mutagen.id3._frames
from mutagen.id3 import ID3, TDRC, TIT2
from mutagen.id3._frames import Frame, TextFrame
from mutagen.mp4 import AtomDataType, MP4Cover, MP4FreeForm, MP4Tags

from ..http import CodeBasedRestException
from ..utils import cached_property, DBCache, cached, get_user_cache_dir, CacheKey, format_duration, is_hangul
from .wiki import Artist, eng_name, split_name

__all__ = [
    "ExtendedMutagenFile", "FakeMusicFile", "iter_music_files", "load_tags", "iter_music_albums",
    "iter_categorized_music_files", "TagException",  "TagAccessException", "UnsupportedTagForFileType",
    "InvalidTagName", "TagValueException", "TagNotFound", "WikiMatchException"
]
log = logging.getLogger("ds_tools.music.files")

NON_MUSIC_EXTS = {"jpg", "jpeg", "png", "jfif", "part", "pdf", "zip"}
PUNC_STRIP_TBL = str.maketrans({c: "" for c in string.punctuation})
TYPED_TAG_MAP = {
    "title": {"mp4": "\xa9nam", "mp3": "TIT2"},
    "date": {"mp4": "\xa9day", "mp3": "TDRC"},
    "genre": {"mp4": "\xa9gen", "mp3": "TCON"},
    "album": {"mp4": "\xa9alb", "mp3": "TALB"},
    "artist": {"mp4": "\xa9ART", "mp3": "TPE1"},
    "album_artist": {"mp4": "aART", "mp3": "TPE2"},
    "track": {"mp4": "trkn", "mp3": "TRCK"},
    "disk": {"mp4": "disk", "mp3": "TPOS"},
}


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
        paths = os.listdir(_path) if os.path.isdir(_path) else [_path]
    else:
        paths = _path

    for file_path in paths:
        music_file = ExtendedMutagenFile(file_path)
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


class FakeMusicFile:
    def __init__(self, sha256sum, tags):
        self.filename = sha256sum
        self.tags = tags

    def tagless_sha256sum(self):
        return self.filename


class ExtendedMutagenFile:
    """Adds some properties/methods to mutagen.File types that facilitate other functions"""
    def __new__(cls, file_path, *args, **kwargs):
        file_path = Path(file_path).as_posix()
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
        pass

    def __getattr__(self, item):
        return getattr(self._f, item)

    def __getitem__(self, item):
        return self._f[item]

    def __repr__(self):
        ftype = "[{}]".format(self.ext) if self.ext is not None else ""
        return "<{}({!r}){}>".format(type(self).__name__, self.filename, ftype)

    def save(self):
        self.tags.save(self._f.filename)

    @property
    def path(self):
        return Path(self._f.filename).resolve()

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
        return album

    @cached_property
    def album_from_dir(self):
        album = self.album_dir
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
        title_key = self.tag_name_to_id("title")
        self.tags[title_key] = title if (self.ext == "mp4") else TIT2(text=title)

    @cached_property
    def tag_artist(self):
        return self.tag_text("artist")

    @cached_property
    def wiki_artist(self):
        try:
            eng, han = split_name(self.tag_artist)
        except ValueError as e:
            log.error("Error splitting into eng+han: {!r}".format(self.tag_artist))
            return None

        # try:
        #     eng = eng_name(self, self.tag_artist, "english_artist")
        # except AttributeError as e:
        #     if is_hangul(self.tag_artist):
        #         try:
        #             eng = eng_name(self, self.artist_dir, "english_artist")
        #         except AttributeError as e:
        #             log.error("{}: Unable to find Wiki artist - unable to parse english name from {!r}".format(self, self.tag_artist))
        #             return None
        #     else:
        #         log.error("{}: Unable to find Wiki artist - unable to parse english name from {!r}".format(self, self.tag_artist))
        #         return None
        #
        lc_dir = self.artist_dir.lower()
        lc_eng = eng.lower()
        if (lc_eng != lc_dir) and (lc_dir in lc_eng):
            collab_indicators = ("and", "&", "feat", ",")
            if any(i in lc_eng for i in collab_indicators):
                log.warning("Using artist {!r} instead of {!r} for {}".format(self.artist_dir, eng, self), extra={"color": "cyan"})
                return Artist(self.artist_dir)
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
                    for member in group.members():
                        member_artist = member[-1]
                        if member_artist and member_artist.english_name.lower() == name:
                            return member_artist

            log.error("Error retrieving information from wiki about artist {!r} for {}: {}".format(eng, self, e))
            return None

    @cached_property
    def wiki_album(self):
        try:
            artist = self.wiki_artist
            album = artist.find_album(self.album_name_cleaned) if artist else None
            if album:
                return album

            if artist:
                song = artist.find_song(self.tag_title)
                if song:
                    self.__dict__["wiki_song"] = song
                    album = song.album
                    log.debug("Matched {} to {} via song".format(self, album))
                    return album
            log.error("Unable to match album {!r} for {}".format(self.album_name_cleaned, self))

            # if artist:
            #     album_name = self.album_name_cleaned.lower().translate(PUNC_STRIP_TBL)
            #     match = self._find_album_match(album_name)
            #     if not match:
            #         if is_hangul(album_name):
            #             album = artist.find_album(self.album_from_dir)
            #             if album:
            #                 return album
            #             album_name = self.album_from_dir.lower().translate(PUNC_STRIP_TBL)
            #             match = self._find_album_match(album_name)
            #
            #     if not match:
            #         for album in artist:
            #             if album.type == "Collaborations" and album.title == self.tag_title:
            #                 return album
            #         log.error("Unable to match album {!r} for {}".format(self.album_name_cleaned, self))
            #     return match
            return None
        except Exception as e:
            log.error("Encountered {} while trying to find wiki album for {}: {}\n{}".format(type(e).__name__, self, e, traceback.format_exc()))
            raise e

    # def _find_album_match(self, title):
    #     candidates = set()
    #     # noinspection PyTypeChecker
    #     for artist_album in self.wiki_artist:
    #         if artist_album.title.lower().translate(PUNC_STRIP_TBL) in title:
    #             candidates.add(artist_album)
    #     if len(candidates) == 1:
    #         match = candidates.pop()
    #         log.debug("Matched album {!r} to {} for {}".format(self.album_name_cleaned, match, self))
    #         return match
    #     elif candidates:
    #         fmt = "Found too many potential album matches for {!r} for {}: {}"
    #         raise WikiMatchException(fmt.format(self.album_name_cleaned, self, ", ".join(map(repr, sorted(candidates)))))
    #     return None

    @cached_property
    def wiki_song(self):
        artist = self.wiki_artist
        try:
            return artist.find_song(self.tag_title, album=self.wiki_album) if artist else None
        except Exception as e:
            log.error("Encountered {} while processing {}: {}".format(type(e).__name__, self, e))
            raise e

    @cached_property
    def wiki_expected_rel_path(self):
        ext = self.ext
        if self.wiki_song:
            return self.wiki_song.expected_rel_path(ext)
        elif self.wiki_album:
            return os.path.join(self.wiki_album.expected_rel_path, self.basename())
        elif self.wiki_artist and ("single" in self.album_type_dir.lower()):
            artist_dir = self.wiki_artist.expected_dirname
            dest = os.path.join(artist_dir, self.album_type_dir, self.album_dir, self.basename())
            log.warning("{}.wiki_expected_rel_path defaulting to {!r}".format(self, dest))
            return dest
        return None

    @cached_property
    def album_path(self):
        """The directory that this file is in"""
        return os.path.dirname(os.path.abspath(self.filename))

    @cached_property
    def album_type_path(self):
        """The directory containing this file's album dir (i.e., 'Albums', 'Mini Albums', 'Singles', etc.)"""
        return os.path.dirname(self.album_path)

    @cached_property
    def artist_path(self):
        """The directory containing this file's album type dir"""
        return os.path.dirname(self.album_type_path)

    @cached_property
    def album_dir(self):
        return os.path.basename(self.album_path)

    @cached_property
    def album_type_dir(self):
        return os.path.basename(self.album_type_path)

    @cached_property
    def artist_dir(self):
        return os.path.basename(self.artist_path)

    @cached_property
    def ext(self):
        if isinstance(self.tags, MP4Tags):
            return "mp4"
        elif isinstance(self.tags, ID3):
            return "mp3"
        return None

    def basename(self, no_ext=False, trim_prefix=False):
        basename = os.path.basename(self.filename)
        if no_ext:
            basename = os.path.splitext(basename)[0]
        if trim_prefix:
            m = re.match("\d+\.?\s+(.*)", basename)
            if m:
                basename = m.group(1)
        return basename

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
            return type2id[self.ext]
        except KeyError as e:
            raise UnsupportedTagForFileType(tag_name, self) from e

    def tags_for_id(self, tag_id):
        """
        :param str tag_id: A tag ID
        :return list: All tags from this file with the given ID
        """
        if self.ext == "mp3":
            return self.tags.getall(tag_id.upper())         # all MP3 tags are uppercase; some MP4 tags are mixed case
        return self.tags[tag_id]                            # MP4Tags doesn't have getall() and always returns a list

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

    def tag_text(self, tag, strip=True, by_id=False):
        """
        :param str tag: The name of the tag to retrieve, or the tag ID if by_id is set to True
        :param bool strip: Strip leading/trailing spaces from the value before returning it
        :param bool by_id: The provided value was a tag ID rather than a tag name
        :return str: The text content of the tag with the given name if there was a single value
        :raises: :class:`TagValueException` if multiple values existed for the given tag
        """
        _tag = self.get_tag(tag, by_id)
        vals = getattr(_tag, "text", _tag)
        if not isinstance(vals, list):
            vals = [vals]
        vals = list(map(str, vals))
        if len(vals) > 1:
            fmt = "Multiple {!r} values found for {}: {}"
            raise TagValueException(fmt.format(tag, self, ", ".join(map(repr, vals))))
        elif not vals:
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
        with open(self.filename, "rb") as f:
            tmp = BytesIO(f.read())

        try:
            mutagen.File(tmp).tags.delete(tmp)
        except AttributeError as e:
            log.error("Error determining tagless sha256sum for {}: {}".format(self.filename, e))
            return self.filename

        tmp.seek(0)
        return sha256(tmp.read()).hexdigest()

    def sha256sum(self):
        with open(self.filename, "rb") as f:
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
        music_file = ExtendedMutagenFile(file_path)
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
#         self._cache = DBCache("acoustid", db_dir=get_user_cache_dir(permissions=0o1777), preserve_old=True)
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


if __name__ == "__main__":
    from ds_tools.logging import LogManager
    from .patches import apply_repr_patches
    apply_repr_patches()
    lm = LogManager.create_default_logger(2, log_path=None, entry_fmt="%(asctime)s %(name)s %(message)s")
