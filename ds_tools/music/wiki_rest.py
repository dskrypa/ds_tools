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
from ..utils import soupify, FSCache, cached, ParentheticalParser
from .exceptions import *

__all__ = ["KpopWikiClient", "WikipediaClient"]
log = logging.getLogger("ds_tools.music.wiki_rest")

JUNK_CHARS = string.whitespace + string.punctuation
STRIP_TBL = str.maketrans({c: "" for c in JUNK_CHARS})


class KpopWikiClient(RestClient):
    __instance = None

    def __new__(cls, *args, **kwargs):
        if cls.__instance is None:
            cls.__instance = super().__new__(cls)
        return cls.__instance

    def __init__(self):
        if not getattr(self, "_KpopWikiClient__initialized", False):
            super().__init__("kpop.fandom.com", rate_limit=1, prefix="wiki")
            self._page_cache = FSCache(cache_subdir="kpop_wiki", prefix="get__", ext="html")
            self._artist_cache = FSCache(cache_subdir="kpop_wiki/artists", prefix="artist__")
            self._error_cache = {}      # Prevent repeated attempts with a bad url within a session
            self.__initialized = True

    @cached("_artist_cache", lock=True, key=lambda s, a: url_quote(a, ""))
    def normalize_artist(self, artist):
        _artist = artist
        artist = artist.replace(" ", "_")
        try:
            html = self.get_page(artist)
        except CodeBasedRestException as e:
            if e.code == 404:
                aae = AmbiguousArtistException(artist, e.resp.text)
                alt = aae.alternative
                if alt:
                    if alt.translate(STRIP_TBL).lower() == _artist.translate(STRIP_TBL).lower():
                        return alt
                    raise aae from e
                else:
                    try:
                        parts = ParentheticalParser().parse(_artist)
                        name = parts[0]
                    except Exception as pe:
                        pass
                    else:
                        log.debug("Checking {!r} for {}".format(name, _artist))
                        try:
                            return self._artist_cache[url_quote(name, "")]
                        except KeyError as ke:
                            pass
            raise e
        else:
            if "This article is a disambiguation page" in html:
                raise AmbiguousArtistException(artist, html)
            return artist

    @cached("_page_cache", lock=True, key=FSCache.dated_html_key_func("%Y-%m"))
    def get_page(self, endpoint, **kwargs):
        if endpoint in self._error_cache:
            raise self._error_cache[endpoint]
        try:
            return self.get(endpoint, **kwargs).text
        except CodeBasedRestException as e:
            log.debug(e)
            self._error_cache[endpoint] = e
            raise e

    @cached(True)
    def parse_categories(self, uri_path):
        page_content = soupify(self.get_page(uri_path))
        cat_ul = page_content.find("ul", class_="categories")
        return {li.text.lower() for li in cat_ul.find_all("li")} if cat_ul else set()


class WikipediaClient(RestClient):
    __instance = None

    def __new__(cls, *args, **kwargs):
        if cls.__instance is None:
            cls.__instance = super().__new__(cls)
        return cls.__instance

    def __init__(self):
        if not getattr(self, "_WikipediaClient__initialized", False):
            super().__init__("en.wikipedia.org", rate_limit=1, prefix="wiki", proto="https")
            self._page_cache = FSCache(cache_subdir="kpop_wiki/wikipedia", prefix="get__", ext="html")
            self.__initialized = True

    @cached("_page_cache", lock=True, key=FSCache.dated_html_key_func("%Y-%m"))
    def get_page(self, endpoint, **kwargs):
        return self.get(endpoint, **kwargs).text

    @cached(True)
    def parse_categories(self, uri_path):
        page_content = soupify(self.get_page(uri_path))
        cat_links = page_content.find("div", id="mw-normal-catlinks")
        cat_ul = cat_links.find("ul") if cat_links else None
        return {li.text.lower() for li in cat_ul.find_all("li")} if cat_ul else set()
