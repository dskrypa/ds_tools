#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
:author: Doug Skrypa
"""

import logging
import string
from urllib.parse import urlparse

from ..exceptions import CodeBasedRestException
from ..http import RestClient
from ..utils import soupify, cached, ParentheticalParser, DBCache
from .exceptions import *
from .utils import parse_aside, parse_infobox, parse_album_page, parse_wikipedia_album_page

__all__ = ["KpopWikiClient", "WikipediaClient"]
log = logging.getLogger("ds_tools.music.wiki_rest")

AMBIGUOUS_URI_PATH_TEXT = [
    "This article is a disambiguation page", "Wikipedia does not have an article with this exact name."
]
JUNK_CHARS = string.whitespace + string.punctuation
STRIP_TBL = str.maketrans({c: "" for c in JUNK_CHARS})


class WikiClient(RestClient):
    _site = None
    _sites = {}
    __instances = {}

    def __init_subclass__(cls, **kwargs):  # Python 3.6+
        if cls._site:
            WikiClient._sites[cls._site] = cls

    def __new__(cls, *args, **kwargs):
        if cls.__instances.get(cls) is None:
            cls.__instances[cls] = super().__new__(cls)
        return cls.__instances[cls]

    def __init__(self, host=None, prefix="wiki", proto="https", **kwargs):
        if not getattr(self, "_WikiClient__initialized", False):
            super().__init__(host or self._site, rate_limit=1, prefix=prefix, proto=proto, **kwargs)
            self._resp_cache = DBCache("responses", cache_subdir="kpop_wiki")
            self._name_cache = DBCache("names", cache_subdir="kpop_wiki")
            self._bad_name_cache = DBCache("invalid_names", cache_subdir="kpop_wiki")
            self.__initialized = True

    @classmethod
    def for_site(cls, site):
        try:
            return cls._sites[site]()
        except KeyError as e:
            raise ValueError("No WikiClient class exists for site {!r}".format(site)) from e

    @cached("_resp_cache", lock=True, key=lambda s, e, *a, **kw: s.url_for(e), exc=True, optional=True)
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

    def parse_side_info(self, soup):
        return {}

    def parse_album_page(self, uri_path, clean_soup, side_info):
        return []


class KpopWikiClient(WikiClient):
    _site = "kpop.fandom.com"

    @cached(True)
    def get_entity_base(self, uri_path, obj_type=None):
        raw = self.get_page(uri_path)
        # if "This article is a disambiguation page" in raw:
        #     raise AmbiguousEntityException(uri_path, raw, obj_type)
        cat_ul = soupify(raw).find("ul", class_="categories")
        return raw, {li.text.lower() for li in cat_ul.find_all("li")} if cat_ul else set()

    def parse_side_info(self, soup):
        return parse_aside(soup)

    def parse_album_page(self, uri_path, clean_soup, side_info):
        return parse_album_page(uri_path, clean_soup, side_info)


class WikipediaClient(WikiClient):
    _site = "en.wikipedia.org"

    @cached(True)
    def get_entity_base(self, uri_path, obj_type=None):
        raw = self.get_page(uri_path)
        if "Wikipedia does not have an article with this exact name." in raw:
            raise AmbiguousEntityException(uri_path, raw, obj_type)
        cat_links = soupify(raw).find("div", id="mw-normal-catlinks")
        cat_ul = cat_links.find("ul") if cat_links else None
        return raw, {li.text.lower() for li in cat_ul.find_all("li")} if cat_ul else set()

    def parse_side_info(self, soup):
        return parse_infobox(soup)

    def parse_album_page(self, uri_path, clean_soup, side_info):
        return parse_wikipedia_album_page(uri_path, clean_soup, side_info)


class DramaWikiClient(WikiClient):
    _site = "wiki.d-addicts.com"

    def __init__(self):
        if not getattr(self, "_DramaWikiClient__initialized", False):
            super().__init__(prefix="", log_params=True)
            self.__initialized = True

    @cached(True)
    def get_entity_base(self, uri_path, obj_type=None):
        raw = self.get_page(uri_path)
        cat_links = soupify(raw).find("div", id="mw-normal-catlinks")
        cat_ul = cat_links.find("ul") if cat_links else None
        return raw, {li.text.lower() for li in cat_ul.find_all("li")} if cat_ul else set()

    def title_search(self, title):
        try:
            resp = self.get("index.php", params={"search": title, "title": "Special:Search"}, use_cached=False)
        except CodeBasedRestException as e:
            log.debug("Error searching for OST {!r}: {}".format(title, e))
            raise e

        url = urlparse(resp.url)
        if url.path != "/index.php":    # If there's an exact match, it redirects to that page
            return url.path[1:]

        soup = soupify(resp.text)
        clean_title = title.translate(STRIP_TBL).lower()
        for a in soup.find(class_="searchresults").find_all("a"):
            if a.text.translate(STRIP_TBL).lower() == clean_title:
                href = a.get("href") or ""
                if href and "redlink=1" not in href:
                    return href
        return None

    @cached("_name_cache", lock=True, key=lambda s, a: "{}: {}".format(s.host, a))
    def normalize_name(self, name):
        return self.title_search(name)