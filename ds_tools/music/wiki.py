#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
:author: Doug Skrypa
"""

import logging
import os
import re
from collections import defaultdict

import bs4

from ..exceptions import CodeBasedRestException
from ..http import RestClient
from ..utils import soupify, FSCache, cached, is_hangul, get_user_cache_dir, contains_hangul

__all__ = ["KpopWikiClient", "Artist", "Album", "Song", "InvalidArtistException"]
log = logging.getLogger("ds_tools.music.wiki")


class Artist:
    def __init__(self, name, page, client, content):
        self._client = client
        self._page = page
        self._content = content
        self.name = name

    def __repr__(self):
        return "<{}({!r})>".format(type(self).__name__, self.name)

    @property
    def english_name(self):
        return eng_name(self, self.name, "english_name")

    @property
    def hangul_name(self):
        return han_name(self, self.name, "hangul_name")

    def members(self):
        members_h2 = self._content.find("span", id="Members").parent
        members_ele = members_h2.next_sibling.next_sibling
        members = []
        if members_ele.name == "ul":
            for li in members_ele:
                m = re.match("(.*?)\s*-\s*(.*)", li.text)
                members.append(tuple(map(str.strip, m.groups())))
        elif members_ele.name == "table":
            for tr in members_ele.find_all("tr"):
                vals = [td.text.strip() for td in tr.find_all("td")]
                if vals:
                    members.append(tuple(map(str.strip, vals)))
        return members

    def __iter__(self):
        yield from self.albums()

    def albums(self):
        discography = self._client.get_discography(self._page)
        for lang, type_albums in discography.items():
            for album_type, albums in type_albums.items():
                for album, (year, uri_path) in albums.items():
                    yield Album(self, album, lang, album_type, year, uri_path, self._client)


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

    def __iter__(self):
        yield from self.tracks()

    def tracks(self):
        if self._tracks is not None:
            return self._tracks
        if not self._page:
            raise AttributeError("{} has no known wiki page from which tracks can be retrieved".format(self))
        tracks = self._client._get_album(self._page)
        if tracks:
            for i, (title, extra, length, addl_info) in enumerate(tracks):
                yield Song(self.artist, self, title, length, extra, addl_info, i + 1)


class Song:
    def __init__(self, artist, album, title, length, extra, addl_info, track_num):
        self.artist = artist
        self.album = album
        self.title = title
        self.length = length
        self.extra = extra
        self.addl_info = addl_info
        self.track = track_num

    def __repr__(self):
        return "<{}({!r} by {})[{}]>".format(type(self).__name__, self.title, self.artist, self.length)

    @property
    def seconds(self):
        m, s = map(int, self.length.split(":"))
        return s + (m * 60)

    @property
    def english_title(self):
        return eng_name(self, self.title, "english_title")

    @property
    def hangul_title(self):
        return han_name(self, self.title, "hangul_title")


class KpopWikiClient(RestClient):
    def __init__(self):
        super().__init__("kpop.wikia.com", rate_limit=1, prefix="wiki")
        self.cache_dir = get_user_cache_dir("kpop_wiki")
        os.path.join(self.cache_dir, "artists")

    @cached(FSCache(cache_subdir="kpop_wiki", prefix="artist__"), lock=True, key=lambda s, a: a)
    def normalize_artist(self, artist):
        try:
            self.get_page(artist)
        except CodeBasedRestException as e:
            if e.code == 404:
                exc_soup = soupify(e.resp.text)
                try:
                    alt = exc_soup.find("span", class_="alternative-suggestion").find("a").text
                except Exception as e1:
                    raise e
                else:
                    if alt.lower() == artist.lower():
                        return alt
                    else:
                        raise InvalidArtistException("Artist {!r} doesn't exist - did you mean {!r}?".format(artist, alt)) from e
        else:
            return artist

    @cached(FSCache(cache_subdir="kpop_wiki", prefix="get__", ext="html"), lock=True, key=FSCache.dated_html_key)
    def get_page(self, endpoint, **kwargs):
        return self.get(endpoint, **kwargs).text

    def get_artist(self, artist, **kwargs):
        artist = self.normalize_artist(artist)
        soup = soupify(self.get_page(artist, **kwargs))
        content = soup.find("div", id="mw-content-text")

        to_remove = ("center", "aside")
        for ele_name in to_remove:
            rm_ele = content.find(ele_name)
            if rm_ele:
                rm_ele.extract()

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

        track_rx = re.compile("\"?(.*?)\"\s*(\(.*?\))?\s*-\s*(\d+:\d{2})\s*\(?(.*)\)?$")
        tracks = []
        for li in ol:
            m = track_rx.match(li.text.strip())
            if m:
                name, note, runtime, addl_info = m.groups()
                tracks.append((name, note, runtime, addl_info))
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
            while not isinstance(ele, bs4.element.Tag):     # Skip past NavigableString objects
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
                        year = year.strip()[1:-1].strip()
                        m = re.match("\(?(\d+)\)?", year)
                        if m:
                            year = m.group(1)
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


def eng_name(obj, name, attr):
    m = re.match("(.*)\s*\((.*)\)", name)
    if m:
        eng, han = m.groups()
        if contains_hangul(eng):
            if contains_hangul(han):
                raise AttributeError("{} Does not have an {}".format(obj, attr))
            return han.strip()
        return eng.strip()
    if contains_hangul(name):
        raise AttributeError("{} Does not have an {}".format(obj, attr))
    return name.strip()


def han_name(obj, name, attr):
    m = re.match("(.*)\s*\((.*)\)", name)
    if m:
        eng, han = m.groups()
        if contains_hangul(han):
            if contains_hangul(eng):
                return name.strip()
            return han.strip()
        if contains_hangul(eng):
            return eng.strip()
    if contains_hangul(name):
        return name.strip()
    raise AttributeError("{} Does not have a {}".format(obj, attr))


class InvalidArtistException(Exception):
    pass


if __name__ == "__main__":
    from ds_tools.logging import LogManager
    lm = LogManager.create_default_logger(2, log_path=None, entry_fmt="%(asctime)s %(name)s %(message)s")
