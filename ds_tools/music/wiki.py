#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
:author: Doug Skrypa
"""

import logging
import re
from collections import defaultdict

import bs4

from ..http import RestClient
from ..utils import soupify, FSCache, cached, is_hangul

__all__ = ["KpopWikiClient", "Artist", "Album", "Song"]
log = logging.getLogger("ds_tools.music.wiki")


class Artist:
    def __init__(self, name, page, client, content):
        self._client = client
        self._page = page
        self._content = content
        self.name = name

    def __repr__(self):
        return "<{}({!r})>".format(type(self).__name__, self.name)

    def members(self):
        members_h2 = self._content.find("span", id="Members").parent
        ul = members_h2.next_sibling.next_sibling
        members = []
        for li in ul:
            m = re.match("(.*?)\s*-\s*(.*)", li.text)
            members.append(tuple(map(str.strip, m.groups())))
        return members

    def albums(self):
        discography = self._client.get_discography(self._page)
        for lang, type_albums in discography.items():
            for album_type, albums in type_albums.items():
                for album, (year, uri_path) in albums.items():
                    yield Album(self, album, lang, album_type, year, uri_path, self._client)


class Song:
    def __init__(self, artist, album, title, length, extra):
        self.artist = artist
        self.album = album
        self.title = title
        self.length = length
        self.extra = extra

    def __repr__(self):
        return "<{}({!r} by {})[{}]>".format(type(self).__name__, self.title, self.artist, self.length)


class Album:
    def __init__(self, artist, title, lang, alb_type, year, uri_path, client):
        self.artist = artist
        self.title = title
        self.language = lang
        self.type = alb_type
        self.year = year
        self._page = uri_path
        self._client = client
        self._tracks = None

    def __repr__(self):
        return "<{}({!r} by {}, {})>".format(type(self).__name__, self.title, self.artist, self.year)

    def tracks(self):
        if self._tracks is not None:
            return self._tracks
        if not self._page:
            raise AttributeError("{} has no known wiki page from which tracks can be retrieved".format(self))
        tracks = self._client._get_album(self._page)
        if tracks:
            for title, extra, length in tracks:
                yield Song(self.artist, self, title, length, extra)


class KpopWikiClient(RestClient):
    def __init__(self):
        super().__init__("kpop.wikia.com", rate_limit=1, prefix="wiki")

    @cached(FSCache(cache_subdir="kpop_wiki", prefix="get__", ext="html"), lock=True, key=FSCache.dated_html_key)
    def get_page(self, endpoint, **kwargs):
        return self.get(endpoint, **kwargs).text

    def get_artist(self, artist, **kwargs):
        soup = soupify(self.get_page(artist, **kwargs))
        content = soup.find("div", id="mw-content-text")
        aside = content.find("aside")
        if aside:
            aside.extract()
        intro = content.text.strip()
        m = re.match("^(.*?)\s*\((.*?)\)", intro)
        if not m:
            raise ValueError("Unexpected intro format: {}".format(intro))
        eng, han = m.groups()
        if not is_hangul(han):
            m = re.match("Korean:\s*([^;]+);", han)
            if not m:
                raise ValueError("Unexpected hangul name format: {}".format(intro))
            han = m.group(1)
        name = "{} ({})".format(eng, han)
        return Artist(name, artist, self, soup)

    def get_all_albums(self, artist, **kwargs):
        albums_by_lang_type = defaultdict(lambda: defaultdict(dict))

        for lang, type_albums in self.get_discography(artist, **kwargs).items():
            for album_type, albums in type_albums.items():
                for album, (year, uri_path) in albums.items():
                    if uri_path:
                        track_list = self._get_album(uri_path, **kwargs)
                    else:
                        track_list = None
                    albums_by_lang_type[lang][album_type][album] = (year, uri_path, track_list)
        return albums_by_lang_type

    def _get_album(self, album, **kwargs):
        soup = soupify(self.get_page(album, **kwargs))
        try:
            track_list_h2 = soup.find("span", id="Track_list").parent
        except AttributeError as e:
            return None
        ol = track_list_h2.next_sibling.next_sibling
        assert ol.name == "ol", "Unexpected element following the Track_list h2"

        track_rx = re.compile("\"?(.*?)\"\s*(\(.*?\))?\s*-\s*(\d+:\d{2})$")
        tracks = []
        for li in ol:
            m = track_rx.match(li.text.strip())
            if m:
                name, note, runtime = m.groups()
                tracks.append((name, note, runtime))
            else:
                raise ValueError("Unexpected value found for track: {}".format(li))

        return tracks

    def get_discography(self, artist, **kwargs):
        """

        :param str artist: An artist as it appears in the URL
        :param kwargs: Additional keyword arguments to pass to :meth:`.get`
        :return dict: Mapping of {language: {album_type: {album: (year, uri_path)}}}
        """
        soup = soupify(self.get_page(artist, **kwargs))
        discography_h2 = soup.find("span", id="Discography").parent

        albums_by_lang_type = defaultdict(lambda: defaultdict(dict))
        lang = "Korean"
        album_type = "Unknown"
        ele = discography_h2.next_sibling
        while True:
            while not isinstance(ele, bs4.element.Tag):
                ele = ele.next_sibling
            if ele.name == "h3":
                lang = next(ele.children).get("id")
            elif ele.name == "h4":
                album_type = next(ele.children).get("id")
            elif ele.name == "ul":
                for li in ele.children:
                    found = 0
                    for a in li.find_all("a"):
                        link = a.get("href")
                        album = a.text
                        if a.parent.name == "li":
                            year = list(a.parent.children)[-1]
                        else:
                            year = a.parent.next_sibling
                        year = year.strip()[1:-1]
                        albums_by_lang_type[lang][album_type][album] = (year, link[6:])
                        found += 1
                    if not found:
                        m = re.match("\"?(.*?)\"?\s* \((\d+)\)$", li.text.strip())
                        if m:
                            album, year = m.groups()
                            albums_by_lang_type[lang][album_type][album] = (year, None)

            elif ele.name in ("h2", "div"):
                break
            ele = ele.next_sibling

        return albums_by_lang_type


if __name__ == "__main__":
    from ds_tools.logging import LogManager
    lm = LogManager.create_default_logger(2, log_path=None, entry_fmt="%(asctime)s %(name)s %(message)s")
