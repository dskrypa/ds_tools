#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
:author: Doug Skrypa
"""

import logging
import os
import pickle
import re
from hashlib import sha256
from io import BytesIO

import mutagen
import mutagen.id3._frames
from mutagen.id3 import ID3, TDRC, TIT2
from mutagen.id3._frames import Frame, TextFrame
from mutagen.mp4 import AtomDataType, MP4Cover, MP4FreeForm, MP4Tags

from ..utils import cached_property

__all__ = [
    "ExtendedMutagenFile", "FakeMusicFile", "iter_music_files", "load_tags", "iter_music_albums",
    "iter_categorized_music_files"
]
log = logging.getLogger("ds_tools.music.files")

NON_MUSIC_EXTS = {"jpg", "jpeg", "png", "jfif", "part", "pdf", "zip"}
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
        ftype = "[{}]".format(self.file_type) if self.file_type is not None else ""
        return "<{}{}({!r})>".format(type(self).__name__, ftype, self.filename)

    @cached_property
    def album_dir(self):
        """The directory that this file is in"""
        return os.path.dirname(os.path.abspath(self.filename))

    @cached_property
    def album_type_dir(self):
        """The directory containing this file's album dir (i.e., 'Albums', 'Mini Albums', 'Singles', etc.)"""
        return os.path.dirname(self.album_dir)

    @cached_property
    def artist_dir(self):
        """The directory containing this file's album type dir"""
        return os.path.dirname(self.album_type_dir)

    @cached_property
    def album_dir_name(self):
        return os.path.basename(self.album_dir)

    @cached_property
    def album_type_dir_name(self):
        return os.path.basename(self.album_type_dir)

    @cached_property
    def artist_dir_name(self):
        return os.path.basename(self.artist_dir)

    @cached_property
    def file_type(self):
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
            raise KeyError("Unconfigured tag name: {}".format(tag_name)) from e
        try:
            return type2id[self.file_type]
        except KeyError as e:
            raise KeyError("Unconfigured tag name for {!r} files: {}".format(self.file_type, tag_name))

    def tags_named(self, tag_name):
        if self.file_type == "mp3":
            return self.tags.getall(self.tag_name_to_id(tag_name))
        return self.tags[self.tag_name_to_id(tag_name)]     # MP4Tags doesn't have getall() and always returns a list

    def tag_named(self, tag_name):
        return self.tags[self.tag_name_to_id(tag_name)]

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

