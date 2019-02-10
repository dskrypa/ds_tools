#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
:author: Doug Skrypa
"""

import logging
import string
from urllib.parse import quote as url_quote

from ..exceptions import CodeBasedRestException
from ..http import RestClient
from ..utils import soupify, FSCache, cached, ParentheticalParser, DBCache
from .exceptions import *

__all__ = ["KpopWikiClient", "WikipediaClient"]
log = logging.getLogger("ds_tools.music.wiki_rest")

AMBIGUOUS_URI_PATH_TEXT = [
    "This article is a disambiguation page", "Wikipedia does not have an article with this exact name."
]
JUNK_CHARS = string.whitespace + string.punctuation
STRIP_TBL = str.maketrans({c: "" for c in JUNK_CHARS})


class WikiClient(RestClient):
    __instances = {}

    def __new__(cls, *args, **kwargs):
        if cls.__instances.get(cls) is None:
            cls.__instances[cls] = super().__new__(cls)
        return cls.__instances[cls]

    def __init__(self, host, prefix="wiki", proto="https"):
        if not getattr(self, "_WikiClient__initialized", False):
            super().__init__(host, rate_limit=1, prefix=prefix, proto=proto)
            self._resp_cache = DBCache("responses", cache_subdir="kpop_wiki")
            self._name_cache = DBCache("names", cache_subdir="kpop_wiki")
            self._bad_name_cache = DBCache("invalid_names", cache_subdir="kpop_wiki")
            self.__initialized = True

    @cached("_resp_cache", lock=True, key=lambda s, e, *a, **kw: s.url_for(e), exc=True)
    def get(self, *args, **kwargs):
        return super().get(*args, **kwargs)

    @cached(True, exc=True)  # Prevent needing to repeatedly unpickle
    def get_page(self, endpoint, **kwargs):
        return self.get(endpoint, **kwargs).text

    @cached("_name_cache", lock=True, key=lambda s, a: "{}: {}".format(s.host, a))
    def normalize_name(self, name):
        name = name.strip()
        if not name:
            raise ValueError("A valid name must be provided")
        _name = name
        name = name.replace(" ", "_")
        try:
            html = self.get_page(name)
        except CodeBasedRestException as e:
            if e.code == 404:
                self._bad_name_cache[name] = True
                aae = AmbiguousEntityException(name, e.resp.text)
                alt = aae.alternative
                if alt:
                    if alt.translate(STRIP_TBL).lower() == _name.translate(STRIP_TBL).lower():
                        return alt
                    raise aae from e
                else:
                    try:
                        parts = ParentheticalParser().parse(_name)
                        name = parts[0]
                    except Exception as pe:
                        pass
                    else:
                        log.debug("Checking {!r} for {}".format(name, _name))
                        try:
                            return self._name_cache["{}: {}".format(self.host, name)]
                        except KeyError as ke:
                            pass

                    for alt in aae.potential_alternatives:
                        if not self._bad_name_cache.get(alt):
                            try:
                                return self.normalize_name(alt)
                            except Exception as ne:
                                pass
            raise e
        else:
            if any(val in html for val in AMBIGUOUS_URI_PATH_TEXT):
                raise AmbiguousEntityException(name, html)
            return name

    normalize_artist = normalize_name


class KpopWikiClient(WikiClient):
    def __init__(self):
        if not getattr(self, "_KpopWikiClient__initialized", False):
            super().__init__("kpop.fandom.com")
            self._artist_cache = FSCache(cache_subdir="kpop_wiki/artists", prefix="artist__")
            self.__initialized = True

    @cached(True)
    def parse_categories(self, uri_path, obj_type=None):
        raw = self.get_page(uri_path)
        # if "This article is a disambiguation page" in raw:
        #     raise AmbiguousEntityException(uri_path, raw, obj_type)
        page_content = soupify(raw)
        cat_ul = page_content.find("ul", class_="categories")
        return {li.text.lower() for li in cat_ul.find_all("li")} if cat_ul else set()


class WikipediaClient(WikiClient):
    def __init__(self):
        if not getattr(self, "_WikipediaClient__initialized", False):
            super().__init__("en.wikipedia.org")
            self.__initialized = True

    @cached(True)
    def parse_categories(self, uri_path, obj_type=None):
        raw = self.get_page(uri_path)
        if "Wikipedia does not have an article with this exact name." in raw:
            raise AmbiguousEntityException(uri_path, raw, obj_type)
        page_content = soupify(raw)
        cat_links = page_content.find("div", id="mw-normal-catlinks")
        cat_ul = cat_links.find("ul") if cat_links else None
        return {li.text.lower() for li in cat_ul.find_all("li")} if cat_ul else set()
