#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
:author: Doug Skrypa
"""

import logging
import os
import re
from collections import OrderedDict
from urllib.parse import urlparse, quote as url_quote
from weakref import WeakValueDictionary

import bs4

from ..exceptions import CodeBasedRestException
from ..http import RestClient
from ..utils import (
    soupify, FSCache, cached, is_hangul, contains_hangul, cached_property, datetime_with_tz, now, strip_punctuation,
    RecursiveDescentParser, UnexpectedTokenError, format_duration
)

__all__ = ["KpopWikiClient", "WikipediaClient", "Artist", "Album", "Song", "InvalidArtistException", "TitleParser"]
log = logging.getLogger("ds_tools.music.wiki")

NUMS = {
    "first": "1st", "second": "2nd", "third": "3rd", "fourth": "4th", "fifth": "5th", "sixth": "6th",
    "seventh": "7th", "eighth": "8th", "ninth": "9th", "tenth": "10th", "debut": "1st"
}
QMARKS = "\"“"


class TitleParser(RecursiveDescentParser):
    _entry_point = "title"
    _strip = True
    TOKENS = OrderedDict([
        ("QUOTE", "[{}]".format(QMARKS)),
        ("LPAREN", "[\(（]"),
        ("RPAREN", "[\)）]"),
        ("DASH", "\s*[-–]\s*"),
        ("TIME", "\d+:\d{2}"),
        ("WS", "\s+"),
        ("TEXT", "[^\"“()（）]+"),
    ])

    def title(self):
        """
        title ::= name { (extra) }* { dash }* { time }* { (extra) }*
        """
        title = {"name": self.name().strip(), "duration": None, "extras": []}
        while self.next_tok:
            if self._accept("LPAREN"):
                title["extras"].append(self.extra())
            elif self._accept("DASH"):
                if self._peek("TIME"):
                    pass
                elif self.tok.value.strip() in self._remaining:
                    title["extras"].append(self.extra("DASH"))
                else:
                    raise UnexpectedTokenError("Unexpected {!r} in {!r}".format(self.next_tok, self._full))
            elif self._accept("WS"):
                pass
            elif self._accept("TIME"):
                title["duration"] = self.tok.value
            elif self._accept("QUOTE") and any(self._full.count(c) % 2 == 1 for c in QMARKS):
                log.warning("Unpaired quote found in {!r}".format(self._full), extra={"red": True})
                pass
            else:
                raise UnexpectedTokenError("Unexpected {!r} in {!r}".format(self.next_tok, self._full))
        return title

    def extra(self, closer="RPAREN"):
        """
        extra ::= ( text | dash | time | quote | (extra) )
        """
        text = ""
        while self.next_tok:
            if self._accept(closer):
                return text
            elif self._accept("LPAREN"):
                text += "({})".format(self.extra())
            else:
                self._advance()
                text += self.tok.value
        return text

    def name(self):
        """
        name :: = { " }* text { (extra) }* { " }*
        """
        had_extra = False
        name = ""
        first_char_was_quote = False
        # quotes = 0
        while self.next_tok:
            if self._peek("TIME") and name:
                return name
            elif self._peek("LPAREN") and name and all(c not in self._full for c in QMARKS):
                return name

            if self._accept("QUOTE"):
                # quotes += 1
                if not name:
                    first_char_was_quote = True
                else:
                    return name
            elif self._accept("DASH"):
                if self._peek("TIME"):
                    return name
                elif self.tok.value.strip() in self._remaining:
                    name += "({})".format(self.extra("DASH"))
                else:
                    name += self.tok.value
            elif self._accept("LPAREN"):
                name += "({})".format(self.extra())
                had_extra = True
            elif self._accept("TEXT") or self._accept("RPAREN"):
                name += self.tok.value
            elif self._accept("WS"):
                if had_extra and not (first_char_was_quote and any(c in self._remaining for c in QMARKS)):
                # if had_extra and not any(self._full.startswith(c) and (self._full.count(c) > 1) for c in QMARKS):
                    return name
                name += self.tok.value
            elif self._accept("TIME"):
                name += self.tok.value
            else:
                raise UnexpectedTokenError("Unexpected {!r} token {!r} in {!r}".format(self.next_tok.type, self.next_tok.value, self._full))
        return name


class AlbumParser(TitleParser):
    _entry_point = "title"
    _strip = True
    TOKENS = OrderedDict([
        ("YEAR", "\(\d{4}\)"),
        ("QUOTE", "[{}]".format(QMARKS)),
        ("LPAREN", "[\(（]"),
        ("RPAREN", "[\)）]"),
        ("DASH", "\s*[-–]\s*"),
        ("WS", "\s+"),
        ("TEXT", "[^\"“()（）]+"),
    ])

    def title(self):
        """
        title ::= name { (extra) }* { dash }* { (time) }* { (extra) }*
        """
        title = {"name": self.name().strip(), "year": None, "extras": []}
        while self.next_tok:
            if self._accept("LPAREN"):
                title["extras"].append(self.extra())
            elif self._accept("DASH"):
                if self.tok.value.strip() in self._remaining:
                    title["extras"].append(self.extra("DASH"))
                else:
                    raise UnexpectedTokenError("Unexpected {!r} in {!r}".format(self.next_tok, self._full))
            elif self._accept("WS"):
                pass
            elif self._accept("YEAR"):
                title["year"] = self.tok.value[1:-1]
            elif self._accept("QUOTE"):
                if any((c not in self._remaining) and (self._full.count(c) % 2 == 1) for c in QMARKS):
                    log.warning("Unpaired quote found in {!r}".format(self._full), extra={"red": True})
                else:
                    raise UnexpectedTokenError("Unexpected {!r} in {!r}".format(self.next_tok, self._full))
            else:
                raise UnexpectedTokenError("Unexpected {!r} in {!r}".format(self.next_tok, self._full))
        return title

    def name(self):
        """
        name :: = { " }* text { (extra) }* { " }*
        """
        had_extra = False
        name = ""
        first_char_was_quote = False
        quotes = 0
        while self.next_tok:
            if self._peek("YEAR"):
                return name
            elif self._peek("LPAREN") and name and (quotes % 2 == 0):
                return name

            if self._accept("QUOTE"):
                quotes += 1
                if not name:
                    first_char_was_quote = True
                elif first_char_was_quote:
                    return name
                else:
                    name += self.tok.value
            elif self._accept("DASH"):
                if self.tok.value.strip() in self._remaining:
                    name += "({})".format(self.extra("DASH"))
                else:
                    name += self.tok.value
            elif self._accept("LPAREN"):
                name += "({})".format(self.extra())
                had_extra = True
            elif self._accept("TEXT") or self._accept("RPAREN"):
                name += self.tok.value
            elif self._accept("WS"):
                if had_extra and not (first_char_was_quote and any(c in self._remaining for c in QMARKS)):
                    return name
                name += self.tok.value
            else:
                raise UnexpectedTokenError("Unexpected {!r} token {!r} in {!r}".format(self.next_tok.type, self.next_tok.value, self._full))
        return name


class WikiObject:
    def __init__(self, uri_path, client):
        if not getattr(self, "_WikiObject__initialized", False):
            self._client = client
            self._uri_path = uri_path
            self.__raw_content = None
            self.__initialized = True

    @cached_property
    def _raw_content(self):
        if not self._uri_path:
            log.log(9, "{} does not have a valid uri_path from which page content could be retrieved".format(self))
            return None
        return self._client.get_page(self._uri_path)

    @property
    def _page_content(self):
        if not self._uri_path:
            raise AttributeError("{} does not have a valid uri_path from which page content could be retrieved".format(self))
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
    __instances = WeakValueDictionary()
    # raw_album_names = set()

    def __new__(cls, artist_uri_path, client=None):
        if client is None:
            client = KpopWikiClient()
            artist_uri_path = client.normalize_artist(artist_uri_path)

        key = (artist_uri_path, client)
        try:
            return cls.__instances[key]
        except KeyError as e:
            cls.__instances[key] = obj = super().__new__(cls)
            return obj

    def __init__(self, artist_uri_path, client=None):
        if client is None:
            client = KpopWikiClient()
            artist_uri_path = client.normalize_artist(artist_uri_path)

        if not getattr(self, "_Artist__initialized", False):
            super().__init__(artist_uri_path, client)
            self.english_name, self.hangul_name, self.stylized_name = self._find_name()
            self.name = "{} ({})".format(self.english_name, self.hangul_name)
            self.feature_tracks = set()
            self.album_parser = AlbumParser()
            self.__initialized = True

    def __lt__(self, other):
        if isinstance(other, str):
            return self.name < other
        elif isinstance(other, type(self)):
            return self.name < other.name
        raise TypeError("'<' not supported for {!r} < {!r}".format(self, other))

    def __gt__(self, other):
        if isinstance(other, str):
            return self.name > other
        elif isinstance(other, type(self)):
            return self.name > other.name
        raise TypeError("'>' not supported for {!r} > {!r}".format(self, other))

    @cached_property
    def expected_dirname(self):
        return self.english_name.replace("/", "_").replace(":", "-").replace("*", "")

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
        yield from sorted(self.albums)

    def _albums(self):
        discography_h2 = self._page_content.find("span", id="Discography").parent
        h_levels = {"h3": "language", "h4": "type"}
        lang = "Korean"
        album_type = "Unknown"
        last_album = None
        ele = discography_h2.next_sibling
        while True:
            while not isinstance(ele, bs4.element.Tag):     # Skip past NavigableString objects
                ele = ele.next_sibling
            val_type = h_levels.get(ele.name)
            if val_type == "language":                      # *almost* always h3, but sometimes type is h3
                val = next(ele.children).get("id")
                val_lc = val.lower()
                if any(v in val_lc for v in ("album", "single", "collaboration", "feature")):
                    h_levels[ele.name] = "type"
                    album_type = val
                else:
                    lang = val
            elif val_type == "type":
                album_type = next(ele.children).get("id")
            elif ele.name == "ul":
                li_eles = list(ele.children)
                while li_eles:
                    li = li_eles.pop(0)
                    ul = li.find("ul")
                    if ul:
                        ul.extract()                            # remove nested list from tree
                        li_eles = list(ul.children) + li_eles   # insert elements from the nested list at top

                    album = self._parse_album(li, album_type, lang, last_album)
                    if album:
                        yield album
                    last_album = album

            elif ele.name in ("h2", "div"):
                break
            ele = ele.next_sibling

    def _parse_album(self, ele, album_type, lang, last_album):
        added_feature_track = False
        year, collabs, addl_info = None, [], []
        ele_text = ele.text.strip()
        # type(self).raw_album_names.add(ele_text)
        base_alb_type = album_type and (album_type[:-2] if re.search("_\d$", album_type) else album_type).lower() or ""
        is_feature_or_collab = base_alb_type in ("features", "collaborations")
        is_ost = base_alb_type in ("ost", "osts")
        if is_feature_or_collab:
            feat_m = re.match("(.*)\s*-\s+(\".*)", ele_text)
            if feat_m:                                          # Matches are most likely single songs, not albums
                collabs.append(feat_m.group(1).strip())
                ele_text = feat_m.group(2).strip()
                # log.debug("{!r} by {} appears to be a collaboration with {!r}".format(ele_text, self, collabs))

        try:
            parsed = self.album_parser.parse(ele_text)
        except UnexpectedTokenError as e:
            log.warning("Unhandled album text format {!r} for {}".format(ele_text, self), extra={"red": True})
            return None
        else:
            album_name = parsed["name"]
            year = parsed["year"]
            for extra in parsed["extras"]:
                if extra.lower().startswith(("with", "feat")):
                    collabs.append(extra)
                else:
                    addl_info.append(extra)

        first_a = ele.find("a")
        if first_a:
            link = first_a.get("href")
            album = first_a.text
            if album_name != album:
                if is_feature_or_collab:  # likely a feature / single with a link to a collaborator
                    self.feature_tracks.add(CollaborationSong(self, album_name, year, collabs, addl_info))
                    added_feature_track = True
                else:
                    log.debug("Unexpected first link text {!r} for album {!r}".format(album, album_name))
                return None

            if not link.startswith("http"):     # If it starts with http, then it is an external link
                return Album(self, album, lang, album_type, year, collabs, addl_info, link[6:], self._client)
            else:
                url = urlparse(link)
                if url.hostname == "en.wikipedia.org":
                    return Album(self, album, lang, album_type, year, collabs, addl_info, url.path[6:], WikipediaClient())
                else:
                    return Album(self, album, lang, album_type, year, collabs, addl_info, None, self._client)
        else:
            if is_ost:
                return Album(self, album_name, lang, album_type, year, collabs, addl_info, None, self._client)
            elif is_feature_or_collab:
                self.feature_tracks.add(CollaborationSong(self, album_name, year, collabs, addl_info))
                added_feature_track = True
            else:
                if last_album and last_album.is_repkg_double_page and (not last_album.is_repackage):
                    if last_album.repackage_name == album_name:
                        return Album(self, album_name, lang, album_type, year, collabs, addl_info, last_album._uri_path, self._client)
                    else:
                        log.warning("{}'s last album seems to be a candidate for original version of a repackage, but {!r} != {!r}".format(self, album_name, last_album.repackage_name), extra={"red": True})
                else:
                    log.log(9, "No album link found for {!r} by {}; last album was: {}".format(album_name, self, last_album))
                return Album(self, album_name, lang, album_type, year, collabs, addl_info, None, self._client)
        # if not is_ost:
        if not added_feature_track:
            log.warning("Unable to parse album from '{}' for {}".format(ele, self), extra={"red": True})
        return None

    @cached_property
    def albums(self):
        return list(self._albums())

    def album_for_uri(self, uri_path):
        for album in self:
            if album._uri_path == uri_path:
                return album
        return None

    def find_album(self, title, album_type=None):
        lc_title = title.lower()
        for album in self:
            if (album.title == title) and ((album_type is None) or (album_type == album._type)):
                return album
        log.debug("No exact {} album match found for title {!r}, trying lower case...".format(self, title))
        # If no exact match was found, try again with lower case titles
        for album in self:
            if (album.title.lower() == lc_title) and ((album_type is None) or (album_type == album._type)):
                return album
        return None
        # err_fmt = "Unable to find an album from {} of type {!r} with title {!r}"
        # raise AlbumNotFoundException(err_fmt.format(self, album_type or "any", title))


class CollaborationSong:
    def __init__(self, artist, title, year, collaborators, addl_info):
        self.artist = artist
        self.title = title
        self.year = year
        self.collaborators = collaborators
        self.addl_info = addl_info

    def __repr__(self):
        cls = type(self).__name__
        collabs = "[{}]".format("".join("({})".format(e) for e in self.collaborators)) if self.collaborators else ""
        return "<{}'s {}({!r}){}>".format(self.artist, cls, self.title, collabs)


class Album(WikiObject):
    """An album by a K-Pop :class:`Artist`.  Should not be initialized manually - use :attr:`Artist.albums`"""
    track_with_artist_rx = re.compile("[\"“]?(.*?)[\"“]?\s*\((.*?)\)$")
    type_map = {
        "mini_album": "Mini Album", "single": "Single", "digital_single": "Single", "special_single": "Single",
        "single_album": "Single Album", "studio_album": "Album", "collaboration": "Collaboration",
        "promotional_single": "Single", "special_album": "Special Album", "ost": "Soundtrack",
        "feature": "Collaboration", "best_album": "Compilation", "live_album": "Live", "other_release": "Other",
        "collaborations_and_feature": "Collaboration", "collaboration_single": "Collaboration",
        "remake_album": "Remake Album", # Album that contains only covers of other artists' songs
    }
    # raw_track_names = set()

    def __init__(self, artist, title, lang, alb_type, year, collaborators, addl_info, uri_path, client):
        super().__init__(uri_path, client)
        self.artist = artist                # may end up being a str when using an alternate wiki client
        self.title = title
        self.language = lang
        if alb_type:
            alb_type = alb_type.lower()
        self._type = alb_type[:-1] if alb_type and alb_type.endswith("s") else alb_type
        self.year = year
        if collaborators:
            self.collaborators = [collaborators] if isinstance(collaborators, str) else collaborators
        else:
            self.collaborators = []
        self.addl_info = addl_info
        self.__num = None
        self.__is_repackage = None
        self._repackage_of = None
        self.__repackage_double_page = False
        self.__repackage_name = None
        self.title_parser = TitleParser()

    def __lt__(self, other):
        if isinstance(other, type(self)):
            return (self.artist, self.title) < (other.artist, other.title)
        raise TypeError("'<' not supported for {!r} < {!r}".format(self, other))

    def __gt__(self, other):
        if isinstance(other, type(self)):
            return (self.artist, self.title) > (other.artist, other.title)
        raise TypeError("'>' not supported for {!r} > {!r}".format(self, other))

    def __repr__(self):
        return "<{}'s {}({!r})[{}]>".format(self.artist, type(self).__name__, self.title, self.year)

    def __iter__(self):
        yield from sorted(self.tracks)

    def _process_intro(self):
        if not self._raw_content:
            self.__is_repackage = False
            return

        num = None
        num_match = re.search("is the (.*)album.+by", self._raw_content)
        if num_match:
            num = num_match.group(1).split()[0].lower().strip()
            repkg_match = re.search("A repackage titled (.*) (?:was|will be) released", self._raw_content)
            if repkg_match:
                for aside in self._page_content.find_all("aside"):
                    released_h3 = aside.find("h3", text="Released")
                    if released_h3:
                        dates_div = released_h3.next_sibling.next_sibling
                        for s in dates_div.stripped_strings:
                            if s.lower().endswith("(repackage)"):
                                self.__repackage_double_page = True
                                break

                repackage_title = soupify(repkg_match.group(1).strip()).text
                self.__repackage_name = repackage_title
                self.__is_repackage = repackage_title.lower() == self.title.lower()
            else:
                self.__is_repackage = False
        else:
            repkg_match = re.search("is a (?:repackage|new edition) of .*'s? (.*)album", self._raw_content)
            self.__is_repackage = bool(repkg_match)
            if repkg_match:
                num = repkg_match.group(1).split()[0].lower().strip()
        self.__num = NUMS.get(num, num)

        if self.__is_repackage:
            self.__repackage_name = self.title
            content = self._page_content.find("div", id="mw-content-text")
            aside = content.find("aside")
            aside.extract()
            for i, a in enumerate(content.find_all("a")):
                href = a.get("href")[6:]
                if href != self.artist._uri_path:
                    self._repackage_of = self.artist.album_for_uri(href)
                    break

            if not self._repackage_of:
                for album in self.artist:
                    if (album != self) and album.repackage_name == self.title:
                        self._repackage_of = album
                        break

    @cached_property
    def is_repackage(self):
        if self.__is_repackage is None:
            self._process_intro()
        return self.__is_repackage

    @property
    def repackage_of(self):
        if self.__is_repackage is None:
            self._process_intro()
        return self._repackage_of

    @cached_property
    def repackage_name(self):
        if self.__is_repackage is None:
            self._process_intro()
        return self.__repackage_name

    @cached_property
    def is_repkg_double_page(self):
        if self.__is_repackage is None:
            self._process_intro()
        return self.__repackage_double_page

    @cached_property
    def _num(self):
        if self.__is_repackage is None:
            self._process_intro()
        return self.__num

    @cached_property
    def type(self):
        lang = ""
        _type = self._type
        if _type.endswith("s"):
            _type = _type[:-1]
        if re.search("_\d$", _type):
            _type = _type[:-2]
            lang = self.language if self.language else ""
            if not lang:
                log.warning("{}: No language detected for _2 type: {!r}".format(self, _type), extra={"red": True})
            else:
                lang += " "
        if _type.endswith("s"):
            _type = _type[:-1]

        if _type not in self.type_map:
            log.warning("{}: Unhandled type: {!r}".format(self, _type), extra={"red": True})
        return "{}{}".format(lang, self.type_map.get(_type, "SORT_ME") + "s")

    @cached_property
    def expected_album_dirname(self):
        title = self.title
        if self.type in ("Albums", "Mini Albums", "Special Albums", "Japanese Albums", "Japanese Mini Albums", "Single Albums", "Remake Albums"):
            try:
                rel_date = self.release_date.strftime("%Y.%m.%d")
            except AttributeError as e:
                rel_date = None

            num = self._num
            if not num:
                if self._raw_content:
                    log.warning("Unable to find album number for {} {}".format(self.type, self), extra={"red": True})
            else:
                _type = self.type[:-1] if self.type.endswith("s") else self.type
                if self.is_repackage:
                    _type += " Repackage"
                if rel_date:
                    title = "[{}] {} [{} {}]".format(rel_date, title, num, _type)
                else:
                    title = "{} [{} {}]".format(title, num, _type)

        return re.sub("[*;]", "", os.path.join(self.type, title).replace("/", "_").replace(":", "-"))

    @cached_property
    def expected_dirname(self):
        artist_dir = self.artist.expected_dirname if hasattr(self.artist, "expected_dirname") else self.artist
        return os.path.join(artist_dir, self.expected_album_dirname)

    def _tracks_from_wikipedia(self):
        num_strs = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9}
        # If this is using the WikipediaClient, then it's likely for a non-Korean artist
        page_content = self._page_content
        side_bar = page_content.find("table", class_=re.compile("infobox vevent.*"))
        desc = side_bar.find("th", class_="description")
        alb_type = self._type
        for ele in desc:
            if str(ele).strip() == "by":
                alb_type = ele.previous_sibling.text.lower()
                self.artist = ele.next_sibling.text
                break

        try:
            track_list_h2 = page_content.find("span", id="Track_listing").parent
        except AttributeError as e:
            if alb_type == "single":
                len_th = side_bar.find("th", text="Length")
                runtime = len_th.next_sibling.text
                yield Song(self.artist, self, self.title, runtime, None, 1)
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
                            yield Song(self.artist, self, title, runtime, [note, song_edition], track_num, disk_num=disk)

                ele = ele.next_sibling

    def _fix_artist(self, page_content=None):
        if page_content is None:
            page_content = self._page_content
        aside = page_content.find("aside")
        artist_h3 = aside.find("h3", text="Artist")
        if artist_h3:
            artist_div = artist_h3.next_sibling.next_sibling
            artists = list(artist_div)                      # will be a single str or multiple html elements
            if len(artists) == 1:
                artist = artists[0].text if hasattr(artists[0], "text") else str(artists[0])
                artist_eng_name = self.artist.english_name
                if (artist_eng_name in artist) and any(artist.count(d) > artist_eng_name.count(d) for d in ",;"):
                    return
                elif any((val in artist) and (val not in artist_eng_name) for val in ("feat", "with")):
                    return

                try:
                    self.artist = Artist(artist)
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

    def _parse_song(self, ele, song_str, track_num, common_addl_info=None):
        # log.debug("Parsing song info from: {!r}".format(song_str))
        # type(self).raw_track_names.add(song_str)
        try:
            parsed = self.title_parser.parse(song_str)
        except UnexpectedTokenError as e:
            log.error("Unable to parse song title for {!r} by {}".format(song_str, self))
            raise e

        if "(" in parsed["name"]:
            re_parsed = self.title_parser.parse(parsed["name"])
            if not ((len(re_parsed["extras"]) == 1) and is_hangul(re_parsed["extras"][0])):
                parsed["name"] = re_parsed["name"]
                parsed["extras"] = re_parsed["extras"] + parsed["extras"]

        if common_addl_info:
            parsed["extras"].append(common_addl_info)

        if not parsed["duration"]:
            track_with_artist_m = self.track_with_artist_rx.match(song_str)
            if track_with_artist_m:
                anchors = list(ele.find_all("a"))
                if anchors:
                    a = anchors[-1]
                    if song_str.endswith("({})".format(a.text)):
                        artist_obj = Artist(a.get("href")[6:], self._client)
                        if parsed["extras"] and a.text in parsed["extras"]:
                            parsed["extras"].remove(a.text)
                        return Song(artist_obj, self, parsed["name"], parsed["duration"], parsed["extras"], track_num)

        return Song(self.artist, self, parsed["name"], parsed["duration"], parsed["extras"], track_num)

    def _tracks(self):
        if isinstance(self._client, WikipediaClient):
            yield from self._tracks_from_wikipedia()
        else:
            if not self._uri_path:
                log.log(9, "No album page exists for {}".format(self))
                return

            page_content = self._page_content
            self._fix_artist(page_content)
            track_list_span = page_content.find("span", id="Track_list")
            if not track_list_span:
                if ("single" in self._type) or (self._type in ("other_release", "collaboration", "feature")):
                    content = page_content.find("div", id="mw-content-text")
                    aside = content.find("aside")
                    aside.extract()
                    m = re.match("^\"?(.*?)\"?\s*\((.*?)\)", content.text.strip())
                    title = "{} ({})".format(*m.groups()) if m else self.title
                    len_h3 = aside.find("h3", text="Length")
                    if len_h3:
                        runtime = len_h3.next_sibling.next_sibling.text
                    else:
                        runtime = "-1:00"
                        log.warning("Unable to find single length in aside for {}".format(self))
                    yield Song(self.artist, self, title, runtime, None, None, 1)
                    return
                else:
                    rel_date = self.release_date.strftime("%Y-%m-%d")
                    if self.release_date > now(as_datetime=True):
                        log.debug("{} had no content, but it will not be released until {}".format(self, rel_date))
                        return
                    elif rel_date == now("%Y-%m-%d"):
                        log.debug("{} had no content, but it was not released until today".format(self))
                        return
                    raise TrackDiscoveryException("Unexpected content on page for {} ({})".format(self, self._type))

            track_list_h2 = track_list_span.parent
            if self._type == "ost":
                ele = track_list_h2.next_sibling
                part = None
                while ele.name not in ("h3", "h2"):
                    if ele.name == "dl":
                        dt = ele.find("dt")
                        if not dt:
                            if ele.find("dd"):  # Nothing left on the page
                                return
                            raise ValueError("Unexpected OST part section in {}: {}".format(self, ele))
                        m = re.match("(.*?Part\s*.*?)\s*\(?", dt.text, re.IGNORECASE)
                        if m:
                            part = m.group(1)
                        else:
                            raise ValueError("Unexpected OST part section in {}".format(self))
                    elif ele.name == "ol":
                        for track_num, li in enumerate(ele):
                            yield self._parse_song(li, li.text.strip(), track_num + 1, part)
                    ele = ele.next_sibling
            else:
                ol = track_list_h2.next_sibling.next_sibling
                if ol.name != "ol":
                    ol = ol.next_sibling.next_sibling
                    assert ol.name == "ol", "Unexpected elements following the Track_list h2"

                if self.is_repkg_double_page:
                    if self.is_repackage:
                        orig_tracks = ol
                        section_header = ol.next_sibling.next_sibling
                        lc_title = self.title.lower()
                        try:
                            while not any(txt in section_header.text.lower() for txt in (lc_title, "repackage")):
                                try:
                                    section_header = section_header.next_sibling.next_sibling.next_sibling.next_sibling
                                except Exception as e:
                                    raise ValueError("Unable to find repackaged track list for {}".format(self)) from e
                        except AttributeError as e:
                            log.error("AttributeError processing double repackage page for {} in {}".format(self, section_header))
                            raise e

                        new_tracks = section_header.next_sibling.next_sibling
                        assert new_tracks.name == "ol", "Unexpected elements following original album tracks on double repackage page"

                        orig_count, new_count = len(orig_tracks), len(new_tracks)
                        if orig_count > new_count:
                            if orig_count > 6 and (orig_count - new_count) < 3:
                                track_lists = (new_tracks,)
                            else:
                                track_lists = (orig_tracks, new_tracks)
                        else:
                            track_lists = (new_tracks,)

                        for ol in track_lists:
                            for track_num, li in enumerate(ol):
                                yield self._parse_song(li, li.text.strip(), track_num + 1)
                    else:
                        for track_num, li in enumerate(ol):
                            yield self._parse_song(li, li.text.strip(), track_num + 1)
                else:
                    for track_num, li in enumerate(ol):
                        yield self._parse_song(li, li.text.strip(), track_num + 1)

    @cached_property
    def tracks(self):
        return list(self._tracks())

    def find_track(self, title):
        attrs = ("file_title", "title", "inverse_han_eng_title")
        for attr in attrs:
            for track in self:
                if getattr(track, attr) == title:
                    return track

        log.debug("No exact {} track match found for title {!r}, trying lower case...".format(self, title))
        lc_title = title.lower()
        for attr in attrs:
            for track in self:
                if getattr(track, attr).lower() == lc_title:
                    return track

        log.debug("No exact {} lower-case track match found for title {!r}, trying languages...".format(self, title))
        for track in self:
            if title in (track.english_title, track.hangul_title):
                return track
        for track in self:
            if lc_title == track.english_title.lower():
                return track

        log.debug("No exact {} language-specific lower-case track match found for title {!r}, trying without punctuation...".format(self, title))
        no_punc = strip_punctuation(lc_title)
        for track in self:
            track_no_punc = strip_punctuation(track.english_title + "".join(track.extras)).lower()
            if no_punc == track_no_punc:
                return track
            # else:
            #     log.debug("{!r} != {!r}".format(no_punc, track_no_punc))

        return None
        # raise ValueError("Unable to find a song from {} with title {!r}".format(self, title))

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
        log.log(9, "{}: Found releases: {}".format(self, ", ".join(rels)))
        return min(dates.keys())

    @cached_property
    def length(self):
        return sum(song.seconds for song in self.tracks)

    @cached_property
    def length_str(self):
        length = format_duration(int(self.length))
        if length.startswith("00:"):
            length = length[3:]
        if length.startswith("0"):
            length = length[1:]
        return length


class Song:
    """A song in an album.  Should not be initialized manually - use :attr:`Album.tracks`"""
    def __init__(self, artist, album, title, length, extras, track_num, disk_num=1):
        self.artist = artist
        self.album = album
        self.title = title
        self.length = length or "-1:00"
        self.extras = extras or []
        self.track = track_num
        self.disk_num = disk_num

    def __lt__(self, other):
        cls = type(self)
        if not isinstance(other, cls):
            raise TypeError("'<' not supported between instances of {!r} and {!r}".format(cls.__name__, type(other).__name__))

        if self.album == other.album:
            return (self.disk_num, self.track) < (other.disk_num, other.track)

        return (self.artist, self.album, self.title) < (other.artist, other.album, other.title)

    def __repr__(self):
        cls = type(self).__name__
        addl = "{}, track {}, disk {}".format(self.length, self.track, self.disk_num)
        if self.extras:
            addl += "][{}".format("".join("({})".format(e) for e in self.extras))
        return "<{}'s {}({!r})[{}]>".format(self.artist, cls, self.title, addl)

    @property
    def seconds(self):
        m, s = map(int, self.length.split(":"))
        return (s + (m * 60)) if m > -1 else 0

    @cached_property
    def english_title(self):
        try:
            return eng_name(self, self.title, "english_title")
        except AttributeError as e:
            return None

    @cached_property
    def hangul_title(self):
        try:
            return han_name(self, self.title, "hangul_title")
        except AttributeError as e:
            return None

    @cached_property
    def inverse_han_eng_title(self):
        if self.hangul_title and self.english_title:
            return "{} ({})".format(self.hangul_title, self.english_title)
        else:
            return self.title

    @cached_property
    def file_title(self):
        parts = [self.title]
        if self.extras:
            parts.extend("({})".format(e) for e in self.extras)
        return " ".join(parts)


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


def unsurround(a_str):
    for a, b in (("\"", "\""), ("(", ")"), ("“", "“")):
        if a_str.startswith(a) and a_str.endswith(b):
            a_str = a_str[1:-1].strip()
    return a_str


class InvalidArtistException(Exception):
    pass


class AlbumNotFoundException(Exception):
    pass


class TrackDiscoveryException(Exception):
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
        if disambig_div:
            return [li.find("a").get("href")[6:] for li in disambig_div.parent.find("ul")]
        return []

    def __str__(self):
        alts = self.alternatives
        if len(alts) == 1:
            return "Artist {!r} doesn't exist - did you mean {!r}?".format(self.artist, alts[0])
        elif alts:
            return "Artist {!r} doesn't exist - did you mean one of these? {}".format(self.artist, " | ".join(alts))
        else:
            return "Artist {!r} doesn't exist and no suggestions could be found."


if __name__ == "__main__":
    from ds_tools.logging import LogManager
    lm = LogManager.create_default_logger(2, log_path=None, entry_fmt="%(asctime)s %(name)s %(message)s")
