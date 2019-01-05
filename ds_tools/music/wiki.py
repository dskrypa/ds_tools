#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
:author: Doug Skrypa
"""

import logging
import re
from urllib.parse import urlparse, quote as url_quote

import bs4

from ..exceptions import CodeBasedRestException
from ..http import RestClient
from ..utils import (
    soupify, FSCache, cached, is_hangul, get_user_cache_dir, contains_hangul, cached_property, datetime_with_tz
)

__all__ = ["KpopWikiClient", "WikipediaClient", "Artist", "Album", "Song", "InvalidArtistException"]
log = logging.getLogger("ds_tools.music.wiki")


class WikiObject:
    def __init__(self, uri_path, client):
        self._client = client
        self._uri_path = uri_path
        self._raw_content = None

    @property
    def _page_content(self):
        if self._raw_content is None:
            if not self._uri_path:
                raise AttributeError("{} does not have a valid uri_path from which page content could be retrieved")
            self._raw_content = self._client.get_page(self._uri_path)
        # soupify every time so that elements may be modified/removed without affecting other functions
        return soupify(self._raw_content)


class Artist(WikiObject):
    """
    A K-Pop artist.

    Iterating over this object will yield the :class:`Album`s from this artist's discography.

    :param str artist_uri_path: The artist name or the uri_path for that artist; if the ``client`` argument is
      provided, then this must be the proper uri_path.
    :param KpopWikiClient client: The :class:`KpopWikiClient` used for retrieving information about this Artist;
      this should not be provided by users.
    """
    def __init__(self, artist_uri_path, client=None):
        if client is None:
            client = KpopWikiClient()
            artist_uri_path = client.normalize_artist(artist_uri_path)
        super().__init__(artist_uri_path, client)
        self.english_name, self.hangul_name, self.stylized_name = self._find_name()
        self.name = "{} ({})".format(self.english_name, self.hangul_name)

    def _find_name(self):
        content = self._page_content.find("div", id="mw-content-text")
        if "This article is a disambiguation page" in self._raw_content:
            raise AmbiguousArtistException(self._uri_path, self._raw_content)
        to_remove = ("center", "aside")
        for ele_name in to_remove:
            rm_ele = content.find(ele_name)
            if rm_ele:
                rm_ele.extract()

        intro = content.text.strip()
        m = re.match("^(.*?)\s+\((.*?)\)", intro)
        if not m:
            raise ValueError("Unexpected intro format: {}".format(intro))
        stylized = None
        eng, han = map(str.strip, m.groups())
        # log.debug("Processing name {!r}/{!r}".format(eng, han))
        if "(" in han and "(" in eng:
            # log.debug("Attempting to extract name with parenthases: {!r}".format(han))
            m = re.match("^(.*)\s*\((.*?\(.*?\).*?)\)", intro)
            if m:
                eng, han = map(str.strip, m.groups())

        if not is_hangul(han):
            stylized_m = re.match("([^;]+);\s*stylized as\s*(.*)", han)
            korean_m = re.match("(?:(?:Korean|Hangul):\s*)?([^;,]+)[;,]", han)
            if stylized_m:
                han, stylized = stylized_m.groups()
            elif korean_m:
                grp = korean_m.group(1)
                if is_hangul(grp):
                    han = grp
                else:
                    m = re.search("(?:Korean|Hangul):(.*?)[,;]", han)
                    if m:
                        han = m.group(1)
                        if not is_hangul(han):
                            msg = "Unexpected hangul name format for {!r}/{!r} in: {}".format(eng, han, intro[:200])
                            raise ValueError(msg)
            else:
                if eng != "yyxy":   # the only exception for now
                    msg = "Unexpected hangul name format for {!r}/{!r} in: {}".format(eng, han, intro[:200])
                    raise ValueError(msg)

        return eng, han.strip(), (stylized.strip() if stylized else stylized)

    def __repr__(self):
        return "<{}({!r})>".format(type(self).__name__, self.stylized_name or self.name)

    def members(self):
        content = self._page_content.find("div", id="mw-content-text")
        members_h2 = content.find("span", id="Members").parent
        members_container = members_h2.next_sibling.next_sibling
        members = []
        if members_container.name == "ul":
            for li in members_container:
                m = re.match("(.*?)\s*-\s*(.*)", li.text)
                members.append(tuple(map(str.strip, m.groups())))
        elif members_container.name == "table":
            for tr in members_container.find_all("tr"):
                vals = [td.text.strip() for td in tr.find_all("td")]
                if vals:
                    members.append(tuple(map(str.strip, vals)))
        return members

    def __iter__(self):
        yield from self.albums

    def _albums(self):
        discography_h2 = self._page_content.find("span", id="Discography").parent
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
                li_eles = list(ele.children)
                while li_eles:
                    li = li_eles.pop(0)
                    ul = li.find("ul")
                    if ul:
                        ul.extract()                            # remove nested list from tree
                        li_eles = list(ele.children) + li_eles  # insert elements from the nested list at top

                    li_text = li.text.strip()
                    plain_m = re.match("\"?(.*?)\"?\s*(?:\([^)]+\))?\s*\([^)]+\)$", li_text)
                    try:
                        album_name = plain_m.group(1)
                    except AttributeError as e:
                        raise ValueError("Unexpected album li format {!r} in: {}".format(li_text, li)) from e

                    found = 0
                    for a in li.find_all("a"):
                        collab = None
                        link = a.get("href")
                        album = a.text
                        if album != album_name:
                            log.debug("Skipping album {!r} != {!r}".format(album, album_name))
                            continue

                        if a.parent.name == "li":
                            year = list(a.parent.children)[-1]
                            collab_m = re.search("\(with ([^\)]+)\)", a.parent.text)
                            if collab_m:
                                collab = collab_m.group(1)
                        else:
                            year = a.parent.next_sibling
                        year = year.strip()[1:-1].strip()
                        m = re.match("\(?(\d+)\)?", year)
                        if m:
                            year = m.group(1)

                        if not link.startswith("http"):     # If it starts with http, then it is an external link
                            yield Album(self, album, lang, album_type, year, collab, link[6:], self._client)
                        else:
                            url = urlparse(link)
                            if url.hostname == "en.wikipedia.org":
                                yield Album(self, album, lang, album_type, year, collab, url.path[6:], WikipediaClient())
                            else:
                                yield Album(self, album, lang, album_type, year, collab, None, self._client)
                        found += 1

                    if not found:
                        m = re.match("\"?(.*?)\"?\s* \((\d+)\)$", li.text.strip())
                        if m:
                            album, year = m.groups()
                            yield Album(self, album, lang, album_type, year, None, None, self._client)

            elif ele.name in ("h2", "div"):
                break
            ele = ele.next_sibling

    @cached_property
    def albums(self):
        return list(self._albums())

    def find_album(self, title, album_type=None):
        lc_title = title.lower()
        for album in self:
            if (album.title == title) and ((album_type is None) or (album_type == album.type)):
                return album
        log.debug("No exact {} album match found for title {!r}, trying lower case...".format(self, title))
        # If no exact match was found, try again with lower case titles
        for album in self:
            if (album.title.lower() == lc_title) and ((album_type is None) or (album_type == album.type)):
                return album
        err_fmt = "Unable to find an album from {} of type {!r} with title {!r}"
        raise AlbumNotFoundException(err_fmt.format(self, album_type or "any", title))


class Album(WikiObject):
    """An album by a K-Pop :class:`Artist`.  Should not be initialized manually - use :attr:`Artist.albums`"""
    def __init__(self, artist, title, lang, alb_type, year, collaborators, uri_path, client):
        super().__init__(uri_path, client)
        self.artist = artist                # may end up being a str when using an alternate wiki client
        self.title = title
        self.language = lang
        if alb_type:
            alb_type = alb_type.lower()
        self.type = alb_type[:-1] if alb_type and alb_type.endswith("s") else alb_type
        self.year = year
        self.collaborators = collaborators

    def __repr__(self):
        return "<{}'s {}({!r})[{}]>".format(self.artist, type(self).__name__, self.title, self.year)

    def __iter__(self):
        yield from self.tracks

    def _tracks_from_wikipedia(self):
        num_strs = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9}
        # If this is using the WikipediaClient, then it's likely for a non-Korean artist
        side_bar = self._page_content.find("table", class_=re.compile("infobox vevent.*"))
        desc = side_bar.find("th", class_="description")
        alb_type = self.type
        for ele in desc:
            if str(ele).strip() == "by":
                alb_type = ele.previous_sibling.text.lower()
                self.artist = ele.next_sibling.text
                break

        try:
            track_list_h2 = self._page_content.find("span", id="Track_listing").parent
        except AttributeError as e:
            if alb_type == "single":
                len_th = desc.find("th", text="Length")
                runtime = len_th.next_sibling.text
                yield Song(self.artist, self, self.title, runtime, None, None, 1)
            else:
                log.warning("Unexpected AttributeError for {}".format(self))
                raise e
        else:
            ele = track_list_h2.next_sibling
            super_edition, edition = None, None
            disk = 1
            while ele.name != "h2":
                if ele.name == "h3":
                    first_span = ele.find("span")
                    if first_span and "edition" in first_span.text.lower():
                        super_edition = first_span.text.strip()
                        edition = None
                    else:
                        raise ValueError("Unexpected value in h3 for {}".format(self))
                elif ele.name == "table":
                    first_th = ele.find("th")
                    if first_th and first_th.text.strip() != "No.":
                        edition_candidate = first_th.text.strip()
                        m = re.match("(.*?)(?:\[[0-9]+\])+$", edition_candidate)  # Strip citations
                        if m:
                            edition_candidate = m.group(1)
                        m = re.match("Dis[ck]\s*(\S+)\s*[-:–]?\s*(.*)", edition_candidate, re.IGNORECASE)
                        if m:
                            disk_str, edition = map(str.strip, m.groups())
                            disk_str = disk_str.lower()
                            try:
                                disk = int(disk_str)
                            except Exception as e:
                                if disk_str in num_strs:
                                    disk = num_strs[disk_str]
                                else:
                                    raise ValueError("Unexpected disc number format for {}: {!r}".format(self, disk_str))
                        else:
                            edition = edition_candidate

                    for tr in ele.find_all("tr"):
                        cells = [td.text.strip() for td in tr.find_all("td")]
                        if len(cells) == 5:
                            try:
                                track_num = int(cells[0][:-1])
                            except Exception as e:
                                raise ValueError("Unexpected format for track number in {}".format(self)) from e
                            title = cells[1]
                            m = re.match("^\"?(.*?)\"?\s*\((.*?)\)", title)
                            if m:
                                title, note = m.groups()
                            else:
                                if title.startswith("\"") and title.endswith("\""):
                                    title = title[1:-1]
                                note = None
                            runtime = cells[-1]
                            if super_edition and edition:
                                song_edition = "{} - {}".format(super_edition, edition)
                            else:
                                song_edition = super_edition or edition
                            yield Song(self.artist, self, title, runtime, note, song_edition, track_num, disk_num=disk)

                ele = ele.next_sibling

    def _tracks(self):
        if isinstance(self._client, WikipediaClient):
            yield from self._tracks_from_wikipedia()
        else:
            try:
                track_list_h2 = self._page_content.find("span", id="Track_list").parent
            except AttributeError as e:
                if not self._uri_path:
                    log.debug("No album page exists for {}".format(self))
                    return

                if self.type in ("single", "digital_single", "other_release"):
                    content = self._page_content.find("div", id="mw-content-text")
                    aside = content.find("aside")
                    aside.extract()
                    m = re.match("^\"?(.*?)\"?\s*\((.*?)\)", content.text.strip())
                    title = "{} ({})".format(*m.groups()) if m else self.title
                    len_h3 = aside.find("h3", text="Length")
                    if len_h3:
                        runtime = len_h3.next_sibling.next_sibling.text
                    else:
                        raise ValueError("Unable to find single length in aside for {}".format(self))
                    yield Song(self.artist, self, title, runtime, None, None, 1)
                else:
                    log.warning("Unexpected AttributeError for {}".format(self))
                    raise e
            else:
                ol = track_list_h2.next_sibling.next_sibling
                if ol.name != "ol":
                    ol = ol.next_sibling.next_sibling
                    assert ol.name == "ol", "Unexpected elements following the Track_list h2"

                aside = self._page_content.find("aside")
                artist_h3 = aside.find("h3", text="Artist")
                if artist_h3:
                    artist_div = artist_h3.next_sibling.next_sibling
                    artists = list(artist_div)                      # will be a single str or multiple html elements
                    if len(artists) == 1:
                        try:
                            self.artist = Artist(artists[0].text if hasattr(artists[0], "text") else str(artists[0]))
                        except AmbiguousArtistException as e:
                            found_alt = False
                            eng_alb_artist = self.artist.english_name.replace(" ", "_")
                            for alt in e.alternatives:
                                if eng_alb_artist in alt:   # Solo artist with common name + group name for disambiguation
                                    found_alt = True
                                    self.artist = Artist(alt)
                                    break
                            if not found_alt:
                                raise e

                track_with_len_rx = re.compile("[\"“]?(.*?)[\"“]\s*(\(.*?\))?\s*-?\s*(\d+:\d{2})\s*\(?(.*)\)?$")
                track_with_artist_rx = re.compile("[\"“]?(.*?)[\"“]\s*\((.*?)\)$")
                track_no_len_rx = re.compile("[\"“]?(.*?)(\(.*?\))?[\"“]\s*\(?(.*)\)?$")
                track_num = 0
                for li in ol:
                    li_text = li.text.strip()
                    track_with_len_m = track_with_len_rx.match(li_text)
                    try_more = True
                    if track_with_len_m:
                        try_more = False
                        title, note, runtime, addl_info = track_with_len_m.groups()
                        track_num += 1
                        yield Song(self.artist, self, title, runtime, note, addl_info, track_num)
                    else:
                        track_with_artist_m = track_with_artist_rx.match(li_text)
                        if track_with_artist_m:
                            title, artist = track_with_artist_m.groups()
                            if artist.lower().strip() not in ("instrumental", "normal edition only", "cd only"):
                                try_more = False
                                track_num += 1
                                yield Song(Artist(artist), self, title, "-1:00", None, None, track_num)

                        if try_more:
                            track_no_len_m = track_no_len_rx.match(li_text)
                            if track_no_len_m:
                                try_more = False
                                title, note, addl_info = track_no_len_m.groups()
                                track_num += 1
                                yield Song(self.artist, self, title, "-1:00", note, addl_info, track_num)

                    if try_more:
                        raise ValueError("Unexpected value found for track: {}".format(li))

    @cached_property
    def tracks(self):
        return list(self._tracks())

    @cached_property
    def release_date(self):
        """
        :return datetime: The `datetime<https://docs.python.org/3/library/datetime.html#datetime-objects>_` object
          representing this album's first release
        """
        dates = {}
        for aside in self._page_content.find_all("aside"):
            released_h3 = aside.find("h3", text="Released")
            if released_h3:
                dates_div = released_h3.next_sibling.next_sibling
                last = None
                for s in dates_div.stripped_strings:
                    try:
                        dt = datetime_with_tz(s, "%B %d, %Y")
                    except Exception as e:
                        if last and not dates[last]:
                            dates[last] = s
                        else:
                            raise ValueError("Unexpected release date value found in: {}".format(dates_div))
                    else:
                        last = dt
                        dates[dt] = None

        if not dates:
            raise ValueError("No release date was found for {}".format(self))

        tfmt = "%Y-%m-%d"
        rels = ["{}: {}".format(dt.strftime(tfmt), t) if t else dt.strftime(tfmt) for dt, t in sorted(dates.items())]
        log.debug("{}: Found releases: {}".format(self, ", ".join(rels)))
        return min(dates.keys())


class Song:
    """A song in an album.  Should not be initialized manually - use :attr:`Album.tracks`"""
    def __init__(self, artist, album, title, length, extra, addl_info, track_num, disk_num=1):
        self.artist = artist
        self.album = album
        self.title = title
        self.length = length
        self.extra = extra
        self.addl_info = addl_info
        self.track = track_num
        self.disk_num = disk_num

    def __repr__(self):
        cls = type(self).__name__
        core = "{!r} [{}]".format(self.title, self.extra) if self.extra else repr(self.title)
        addl = "{}, disk {}".format(self.length, self.disk_num)
        if self.addl_info:
            addl += ", {}".format(self.addl_info)
        return "<{}'s {}({})[{}]>".format(self.artist, cls, core, addl)

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
    __instance = None

    def __new__(cls, *args, **kwargs):
        if cls.__instance is None:
            cls.__instance = super().__new__(cls)
        return cls.__instance

    def __init__(self):
        if not getattr(self, "_KpopWikiClient__initialized", False):
            super().__init__("kpop.wikia.com", rate_limit=1, prefix="wiki")
            self._page_cache = FSCache(cache_subdir="kpop_wiki", prefix="get__", ext="html")
            self.__initialized = True

    @cached(FSCache(cache_subdir="kpop_wiki/artists", prefix="artist__"), lock=True, key=lambda s, a: url_quote(a, ""))
    def normalize_artist(self, artist):
        artist = artist.replace(" ", "_")
        try:
            html = self.get_page(artist)
        except CodeBasedRestException as e:
            if e.code == 404:
                aae = AmbiguousArtistException(artist, e.resp.text)
                alt = aae.alternative
                if alt:
                    if alt.lower() == artist.lower():
                        return alt
                    raise aae from e
            raise e
        else:
            if "This article is a disambiguation page" in html:
                raise AmbiguousArtistException(artist, html)
            return artist

    @cached("_page_cache", lock=True, key=FSCache.dated_html_key_func("%Y-%m"))
    def get_page(self, endpoint, **kwargs):
        return self.get(endpoint, **kwargs).text

    def get_artist(self, artist):
        return Artist(self.normalize_artist(artist), self)


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


class AlbumNotFoundException(Exception):
    pass


class AmbiguousArtistException(Exception):
    def __init__(self, artist, html):
        self.artist = artist
        self.html = html

    @cached_property
    def alternative(self):
        alts = self.alternatives
        return alts[0] if len(alts) == 1 else None

    @cached_property
    def alternatives(self):
        soup = soupify(self.html)
        try:
            return [soup.find("span", class_="alternative-suggestion").find("a").text]
        except Exception as e:
            pass

        disambig_div = soup.find("div", id="disambig")
        return [li.find("a").get("href")[6:] for li in disambig_div.parent.find("ul")]

    def __str__(self):
        alts = self.alternatives
        if len(alts) == 1:
            return "Artist {!r} doesn't exist - did you mean {!r}?".format(self.artist, alts[0])
        return "Artist {!r} doesn't exist - did you mean one of these? {}".format(self.artist, " | ".join(alts))


if __name__ == "__main__":
    from ds_tools.logging import LogManager
    lm = LogManager.create_default_logger(2, log_path=None, entry_fmt="%(asctime)s %(name)s %(message)s")
