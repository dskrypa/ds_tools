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
    soupify, is_hangul, contains_hangul, cached_property, datetime_with_tz, now, UnexpectedTokenError, format_duration,
    ParentheticalParser
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

    def __call__(cls, uri_path, client=None):
        if client is None:
            client = KpopWikiClient()

        url = client.url_for(uri_path)
        categories = client.parse_categories(uri_path)
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

        key = (uri_path, client)
        if key not in WikiEntityMeta._instances:
            obj = expected_cls.__new__(expected_cls, uri_path, client)
            obj.__init__(uri_path, client)
            WikiEntityMeta._instances[key] = obj
        return WikiEntityMeta._instances[key]


class WikiEntity(metaclass=WikiEntityMeta):
    __instances = {}
    _categories = {}
    _category = None

    def __init__(self, uri_path, client=None):
        if not getattr(self, "_WikiEntity__initialized", False):
            self._client = client
            self._uri_path = uri_path
            self._raw_content = client.get_page(uri_path)
            self.name = uri_path
            self.aliases = [self.name]
            self.__initialized = True

    def __repr__(self):
        return "<{}({!r})>".format(type(self).__name__, self.name)

    @property
    def _page_content(self):
        # soupify every time so that elements may be modified/removed without affecting other functions
        return soupify(self._raw_content)

    @property
    def _intro(self):
        try:
            content = self._page_content.find("div", id="mw-content-text")
        except AttributeError as e:
            log.warning(e)
            return None

        to_remove = ("center", "aside")
        for ele_name in to_remove:
            rm_ele = content.find(ele_name)
            if rm_ele:
                rm_ele.extract()

        rm_ele = content.find(class_="dablink")  # disambiguation link
        if rm_ele:
            rm_ele.extract()

        return content


class WikiArtist(WikiEntity):
    _category = ("group", "singer")


class WikiGroup(WikiArtist):
    _category = "group"


class WikiAlbum(WikiEntity):
    _category = "album"


class WikiSinger(WikiArtist):
    _category = "singer"


class WikiSoundtrack(WikiEntity):
    _category = "soundtrack"
