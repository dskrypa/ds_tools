#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
:author: Doug Skrypa
"""

import json
import logging
import os
import re
import string
from contextlib import suppress
from pathlib import Path
from urllib.parse import urlparse
from weakref import WeakValueDictionary

import bs4
from fuzzywuzzy import fuzz, utils as fuzz_utils

from ..utils import (
    soupify, cached_property, datetime_with_tz, now, UnexpectedTokenError, format_duration,
    ParentheticalParser, is_any_cjk, contains_any_cjk
)
from .exceptions import *
from .utils import *
from .wiki_rest import KpopWikiClient, WikipediaClient

__all__ = []
log = logging.getLogger("ds_tools.music.wiki_2")

JUNK_CHARS = string.whitespace + string.punctuation
NUM_STRIP_TBL = str.maketrans({c: "" for c in "0123456789"})
NUMS = {
    "first": "1st", "second": "2nd", "third": "3rd", "fourth": "4th", "fifth": "5th", "sixth": "6th",
    "seventh": "7th", "eighth": "8th", "ninth": "9th", "tenth": "10th", "debut": "1st"
}
STRIP_TBL = str.maketrans({c: "" for c in JUNK_CHARS})


class WikiEntityMeta(type):
    _category_classes = {}
    _category_bases = {}
    _instances = {}

    def __init__(cls, name, bases, attr_dict):
        with suppress(AttributeError):
            # noinspection PyUnresolvedReferences
            category = cls._category
            if category is None or isinstance(category, str):
                WikiEntityMeta._category_classes[category] = cls
            else:
                for cat in category:
                    WikiEntityMeta._category_bases[cat] = cls

        super().__init__(name, bases, attr_dict)

    def __call__(cls, uri_path=None, client=None, *, name=None, **kwargs):
        if client is None:
            client = KpopWikiClient()

        if name and not uri_path:
            uri_path = client.normalize_name(name)

        if uri_path:
            if " " in uri_path:
                uri_path = client.normalize_name(uri_path)
            url = client.url_for(uri_path)
            # log.debug("Using url: {}".format(url))
            # noinspection PyUnresolvedReferences
            expected_cat = cls._category
            # Note: client.parse_categories caches args->return vals
            categories = client.parse_categories(uri_path, expected_cat.title() if isinstance(expected_cat, str) else None)
            if any(i in cat for i in ("albums", "discography article stubs", "singles") for cat in categories):
                category = "album"
            elif any(i in cat for i in ("groups", "group article stubs") for cat in categories):
                category = "group"
            elif any(i in cat for i in ("singers", "person article stubs") for cat in categories):
                category = "singer"
            elif any(i in cat for i in ("osts",) for cat in categories):
                category = "soundtrack"
            else:
                log.debug("Unable to determine category for {}".format(url))
                category = None

            expected_cls = WikiEntityMeta._category_classes[category]
            expected_base = WikiEntityMeta._category_bases.get(category)
            if not issubclass(expected_cls, cls) and not issubclass(expected_base, cls):
                article = "an" if category and category[0] in "aeiou" else "a"
                # noinspection PyUnresolvedReferences
                raise TypeError("{} is {} {} page (expected: {})".format(url, article, category, cls._category))
        else:
            expected_cls = cls

        key = (uri_path, client, name)
        if key not in WikiEntityMeta._instances:
            obj = expected_cls.__new__(expected_cls, uri_path, client)
            # noinspection PyArgumentList
            obj.__init__(uri_path, client, name=name, **kwargs)
            WikiEntityMeta._instances[key] = obj
        return WikiEntityMeta._instances[key]


class WikiEntity(metaclass=WikiEntityMeta):
    __instances = {}
    _categories = {}
    _category = None

    def __init__(self, uri_path=None, client=None, *, name=None, **kwargs):
        # if not getattr(self, "_WikiEntity__initialized", False):
        self._client = client
        self._uri_path = uri_path
        self._raw = client.get_page(uri_path) if uri_path else None
        self.name = name or uri_path
        self.aliases = [self.name]
            # self.__initialized = True

    def __repr__(self):
        return "<{}({!r})>".format(type(self).__name__, self.name)

    @property
    def _soup(self):
        # soupify every time so that elements may be modified/removed without affecting other functions
        return soupify(self._raw) if self._raw else None

    @cached_property
    def _intro(self):
        try:
            content = self._soup.find("div", id="mw-content-text")
        except AttributeError as e:
            log.warning(e)
            return None

        for ele_name in ("center", "aside"):
            rm_ele = content.find(ele_name)
            if rm_ele:
                rm_ele.extract()

        for clz in ("dablink", "hatnote", "shortdescription", "infobox"):
            rm_ele = content.find(class_=clz)
            if rm_ele:
                rm_ele.extract()

        for rm_ele in content.find_all(class_="mw-empty-elt"):
            rm_ele.extract()

        return content


class WikiAlbum(WikiEntity):
    _category = "album"

    def __init__(self, uri_path=None, client=None, **kwargs):
        super().__init__(uri_path, client)


class WikiArtist(WikiEntity):
    _category = ("group", "singer")
    _known_artists = set()
    __known_artists_loaded = False

    def __init__(self, uri_path=None, client=None, *, name=None, strict=True):
        super().__init__(uri_path, client)
        self.english_name, self.cjk_name, self.stylized_name, self.aka = None, None, None, None
        if self._raw:
            try:
                self.english_name, self.cjk_name, self.stylized_name, self.aka = parse_artist_name(self._intro.text)
            except Exception as e:
                if strict:
                    raise e
                log.warning("{} while processing intro for {}: {}".format(type(e).__name__, name or uri_path, e))
        if name and not any(val for val in (self.english_name, self.cjk_name, self.stylized_name)):
            self.english_name, self.cjk_name = split_name(name)

        if self.english_name and self.cjk_name:
            self.name = "{} ({})".format(self.english_name, self.cjk_name)
        else:
            self.name = self.english_name or self.cjk_name

        if self.english_name and isinstance(self._client, KpopWikiClient):
            type(self)._known_artists.add(self.english_name.lower())

    def __repr__(self):
        try:
            return "<{}({!r})>".format(type(self).__name__, self.stylized_name or self.name)
        except AttributeError as e:
            return "<{}({!r})>".format(type(self).__name__, self._uri_path)

    @classmethod
    def known_artist_eng_names(cls):
        if not cls.__known_artists_loaded:
            cls.__known_artists_loaded = True
            known_artists_path = Path(__file__).resolve().parents[2].joinpath("music/artist_dir_to_artist.json")
            with open(known_artists_path.as_posix(), "r", encoding="utf-8") as f:
                artists = json.load(f)
            cls._known_artists.update((split_name(artist)[0].lower() for artist in artists.values()))
            # cls._known_artists.update(map(str.lower, artists.keys()))
        return cls._known_artists

    @classmethod
    def known_artists(cls):
        for name in sorted(cls.known_artist_eng_names()):
            yield WikiArtist(name=name)


class WikiGroup(WikiArtist):
    _category = "group"

    def __init__(self, uri_path=None, client=None, **kwargs):
        super().__init__(uri_path, client, **kwargs)
        self.subunit_of = None

        intro_soup = self._intro
        if re.search("^.* is (?:a|the) .*?sub-?unit of .*?group", intro_soup.text.strip()):
            for i, a in enumerate(intro_soup.find_all("a")):
                try:
                    href = a.get("href")[6:]
                except TypeError as e:
                    href = None
                if href and (href != self._uri_path):
                    self.subunit_of = WikiGroup(href)
                    break

        del self.__dict__["_intro"]

    @cached_property
    def members(self):
        content = self._soup.find("div", id="mw-content-text")
        members_h2 = content.find("span", id="Members").parent
        members_container = members_h2.next_sibling.next_sibling
        members = []
        if members_container.name == "ul":
            for li in members_container:
                a = li.find("a")
                if a:
                    members.append(WikiSinger(a.get("href")[6:]))
                else:
                    m = re.match("(.*?)\s*-\s*(.*)", li.text)
                    member = list(map(str.strip, m.groups()))[0]
                    members.append(member)
        elif members_container.name == "table":
            for tr in members_container.find_all("tr"):
                if tr.find("th"):
                    continue
                a = tr.find("a")
                if a:
                    members.append(WikiSinger(a.get("href")[6:]))
                else:
                    member = list(map(str.strip, (td.text.strip() for td in tr.find_all("td"))))[0]
                    members.append(member)
        return members


class WikiSinger(WikiArtist):
    _category = "singer"

    def __init__(self, uri_path=None, client=None, **kwargs):
        super().__init__(uri_path, client, **kwargs)
        self.member_of = None

        intro_soup = self._intro
        mem_pat = r"^.* is (?:a|the) (.*?)(?:member|vocalist|rapper|dancer|leader|visual|maknae) of .*?group (.*)\."
        mem_match = re.search(mem_pat, intro_soup.text.strip())
        if mem_match:
            if "former" not in mem_match.group(1):
                group_name_text = mem_match.group(2)
                for i, a in enumerate(intro_soup.find_all("a")):
                    if a.text in group_name_text:
                        try:
                            href = a.get("href")[6:]
                        except TypeError as e:
                            href = None
                        if href and (href != self._uri_path):
                            self.member_of = WikiGroup(href)
                            break

        del self.__dict__["_intro"]


class WikiSoundtrack(WikiEntity):
    _category = "soundtrack"

    def __init__(self, uri_path=None, client=None, **kwargs):
        super().__init__(uri_path, client)


if __name__ == "__main__":
    from ds_tools.logging import LogManager
    lm = LogManager.create_default_logger(2, log_path=None, entry_fmt="%(asctime)s %(name)s %(message)s")
