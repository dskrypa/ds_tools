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
import traceback
from collections import OrderedDict
from pathlib import Path
from urllib.parse import urlparse, quote as url_quote
from weakref import WeakValueDictionary

import bs4
# import Levenshtein as lev
from fuzzywuzzy import fuzz, utils as fuzz_utils

from ..exceptions import CodeBasedRestException
from ..http import RestClient
from ..utils import (
    soupify, FSCache, cached, is_hangul, contains_hangul, cached_property, datetime_with_tz, now,
    RecursiveDescentParser, UnexpectedTokenError, format_duration
)

__all__ = ["KpopWikiClient", "WikipediaClient", "Artist", "Album", "Song", "InvalidArtistException", "TitleParser"]
log = logging.getLogger("ds_tools.music.wiki")

JUNK_CHARS = string.whitespace + string.punctuation
NUM_STRIP_TBL = str.maketrans({c: "" for c in "0123456789"})
NUMS = {
    "first": "1st", "second": "2nd", "third": "3rd", "fourth": "4th", "fifth": "5th", "sixth": "6th",
    "seventh": "7th", "eighth": "8th", "ninth": "9th", "tenth": "10th", "debut": "1st"
}
PATH_SANITIZATION_DICT = {c: "" for c in "*;?<>"}
PATH_SANITIZATION_DICT.update({"/": "_", ":": "-", "\\": "_", "|": "-"})
PATH_SANITIZATION_TABLE = str.maketrans(PATH_SANITIZATION_DICT)
STRIP_TBL = str.maketrans({c: "" for c in JUNK_CHARS})
QMARKS = "\"“"


class ParentheticalParser(RecursiveDescentParser):
    _entry_point = "content"
    _strip = True
    _opener2closer = {"LPAREN": "RPAREN", "LBPAREN": "RBPAREN", "LBRKT": "RBRKT", "QUOTE": "QUOTE"}
    _nested_fmts = {"LPAREN": "({})", "LBPAREN": "({})", "LBRKT": "[{}]", "QUOTE": "{!r}"}
    _content_tokens = ["TEXT", "WS"] + list(_opener2closer.values())
    TOKENS = OrderedDict([
        ("QUOTE", "[{}]".format(QMARKS)),
        ("LPAREN", "\("),
        ("RPAREN", "\)"),
        ("LBPAREN", "（"),
        ("RBPAREN", "）"),
        ("LBRKT", "\["),
        ("RBRKT", "\]"),
        ("WS", "\s+"),
        ("TEXT", "[^\"“()（）\[\]]+"),
    ])

    def parenthetical(self, closer="RPAREN"):
        """
        parenthetical ::= ( { text | WS | ( parenthetical ) }* )
        """
        text = ""
        nested = False
        while self.next_tok:
            if self._accept(closer):
                return text, nested
            elif any(self._accept(tok_type) for tok_type in self._opener2closer):
                tok_type = self.tok.type
                text += self._nested_fmts[tok_type].format(self.parenthetical(self._opener2closer[tok_type])[0])
                nested = True
            else:
                self._advance()
                text += self.tok.value
        return text, nested

    def content(self):
        """
        content :: = text { (parenthetical) }* { text }*
        """
        text = ""
        parts = []
        while self.next_tok:
            if any(self._accept(tok_type) for tok_type in self._opener2closer):
                tok_type = self.tok.type
                if tok_type == "QUOTE":
                    if any((c not in self._remaining) and (self._full.count(c) % 2 == 1) for c in QMARKS):
                        log.debug("Unpaired quote found in {!r}".format(self._full))
                        continue

                if text:
                    parts.append(text)
                    text = ""
                parenthetical, nested = self.parenthetical(self._opener2closer[tok_type])
                if not parts and not nested and not self._peek("WS"):
                    text += self._nested_fmts[tok_type].format(parenthetical)
                else:
                    parts.append((parenthetical, nested, tok_type))
            elif any(self._accept(tok_type) for tok_type in self._content_tokens):
                text += self.tok.value
            else:
                raise UnexpectedTokenError("Unexpected {!r} token {!r} in {!r}".format(
                    self.next_tok.type, self.next_tok.value, self._full
                ))

        if text:
            parts.append(text)

        single_idxs = set()
        had_nested = False
        for i, part in enumerate(parts):
            if isinstance(part, tuple):
                nested = part[1]
                had_nested = had_nested or nested
                if not nested:
                    single_idxs.add(i)

        if had_nested and single_idxs:
            single_idxs = sorted(single_idxs)
            while single_idxs:
                i = single_idxs.pop(0)
                for ti in (i - 1, i + 1):
                    if ti < 0:
                        continue
                    if isinstance(parts[ti], str):
                        parenthetical, nested, tok_type = parts[i]
                        formatted = self._nested_fmts[tok_type].format(parenthetical)
                        parts[ti] = (formatted + parts[ti]) if ti > i else (parts[ti] + formatted)
                        parts.pop(i)
                        single_idxs = [idx - 1 for idx in single_idxs]
                        break

        return [part for part in map(str.strip, (p[0] if isinstance(p, tuple) else p for p in parts)) if part]


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

        rm_ele = content.find(class_="dablink")     # disambiguation link
        if rm_ele:
            rm_ele.extract()

        return content


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
    __known_artists_loaded = False
    _known_artists = set()
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
            _intro = self._process_intro()
            self.english_name, self.hangul_name, self.stylized_name, self.subunit_of, self.member_of = _intro
            if self.english_name and self.hangul_name:
                self.name = "{} ({})".format(self.english_name, self.hangul_name)
            else:
                self.name = self.english_name or self.hangul_name
            self.feature_tracks = set()
            self._album_parser = AlbumParser()
            if isinstance(self._client, KpopWikiClient):
                type(self)._known_artists.add(self.english_name.lower())
            self.__initialized = True

    @classmethod
    def known_artist_names(cls):
        if not cls.__known_artists_loaded:
            cls.__known_artists_loaded = True
            known_artists_path = Path(__file__).resolve().parents[2].joinpath("music/artist_dir_to_artist.json")
            with open(known_artists_path.as_posix(), "r", encoding="utf-8") as f:
                artists = json.load(f)
            cls._known_artists.update(map(str.lower, artists.keys()))
        return cls._known_artists

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
        return sanitize(self.english_name)

    def _process_intro(self):
        if (self._raw_content is not None) and ("This article is a disambiguation page" in self._raw_content):
            raise AmbiguousArtistException(self._uri_path, self._raw_content)

        intro = self._intro.text.strip()
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
                if eng not in ("yyxy", "iKON"):
                    msg = "Unexpected hangul name format for {!r}/{!r} in: {}".format(eng, han, intro[:200])
                    raise ValueError(msg)

        subunit_of = None
        if re.search("^.* is (?:a|the) .*?sub-?unit of .*?group", intro):
            for i, a in enumerate(self._intro.find_all("a")):
                try:
                    href = a.get("href")[6:]
                except TypeError as e:
                    href = None
                if href and (href != self._uri_path):
                    subunit_of = Artist(href)
                    break

        member_of = None
        mem_pat = r"^.* is (?:a|the) .*?(?:member|vocalist|rapper|dancer|leader|visual|maknae) of .*?group (.*)\."
        mem_match = re.search(mem_pat, intro)
        if mem_match:
            group_name_text = mem_match.group(1)
            for i, a in enumerate(self._intro.find_all("a")):
                if a.text in group_name_text:
                    try:
                        href = a.get("href")[6:]
                    except TypeError as e:
                        href = None
                    if href and (href != self._uri_path):
                        member_of = Artist(href)
                        break

        return eng, han.strip(), (stylized.strip() if stylized else stylized), subunit_of, member_of

    def __repr__(self):
        try:
            return "<{}({!r})>".format(type(self).__name__, self.stylized_name or self.name)
        except AttributeError as e:
            return "<{}({!r})>".format(type(self).__name__, self._uri_path)

    @cached_property
    def name_with_context(self):
        if self.member_of:
            return "{} [{}]".format(self.name, self.member_of.name)
        elif self.subunit_of:
            pass
        return self.name

    @cached_property
    def members(self):
        content = self._page_content.find("div", id="mw-content-text")
        members_h2 = content.find("span", id="Members").parent
        members_container = members_h2.next_sibling.next_sibling
        members = []
        if members_container.name == "ul":
            for li in members_container:
                a = li.find("a")
                if a:
                    members.append(Artist(a.get("href")[6:]))
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
                    members.append(Artist(a.get("href")[6:]))
                else:
                    member = list(map(str.strip, (td.text.strip() for td in tr.find_all("td"))))[0]
                    members.append(member)
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
            full_break = False
            while not isinstance(ele, bs4.element.Tag):     # Skip past NavigableString objects
                if ele is None:
                    full_break = True
                    break
                ele = ele.next_sibling
            if full_break:
                break

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
            parsed = self._album_parser.parse(ele_text)
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
            link = first_a.get("href") or ""
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
                    album = Album(self, album, lang, album_type, year, collabs, addl_info, url.path[6:], WikipediaClient())
                    # noinspection PyStatementEffect
                    album.tracks    # process page to possibly fix title
                    return album
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
        for album in self.albums:
            if album._uri_path == uri_path:
                return album
        return None

    def __find_album(self, title, album_type=None, threshold=55):
        albums = [album for album in self if (album_type is None) or (album_type == album._type)]
        closest, score = _find_album(title, albums)
        if score == 0:
            log.debug("{}: No albums were found with a title similar to {!r}".format(self, title))
            return None, score

        msg = "{}: The album closest to {!r}: {} (score: {})".format(self, title, closest, score)
        if score < threshold:
            log.debug(msg + " - not being considered a match because score < {}".format(threshold))
            return None, score
        log.debug(msg)
        return closest, score

    def _find_album(self, title, *args, **kwargs):
        return self.__find_album(title, *args, **kwargs)
        # try_again = True
        # while try_again:
        #     try_again = False
        #     closest, score = self.__find_album(title, *args, **kwargs)
        #     if closest is not None:
        #         return closest, score
        #
        #     lc_title = title.lower()
        #     if title.lower().startswith("jelly box"):
        #         title = title[9:].strip()
        #         try_again = True
        #     elif any(title.endswith(val) for val in (self.english_name, self.hangul_name)):
        #         for val in (self.english_name, self.hangul_name):
        #             if title.endswith(val):
        #                 title = title[:-len(val)].strip()
        #                 try_again = True
        #                 break
        #     elif re.search("prod\.? by", lc_title):
        #         try:
        #             parts = ParentheticalParser().parse(title)
        #         except Exception as e:
        #             pass
        #         else:
        #             for i, part in enumerate(parts):
        #                 if all(val in part.lower() for val in ("prod", "by")):
        #                     parts.pop(i)
        #                     break
        #             title = " ".join(parts)
        #             try_again = bool(title)
        #
        #     if not try_again:
        #         return closest, score

    def find_album(self, *args, **kwargs):
        return self._find_album(*args, **kwargs)[0]

    def _find_song(self, title, album=None, album_type=None, feat_only=False, threshold=55, track=None):
        if album and not isinstance(album, Album):
            album = self.find_album(album, album_type)

        if album:
            return album._find_track(title, threshold, track)
        else:
            closest, score = _find_song(title, [] if feat_only else self, self.feature_tracks)
            if score == 0:
                log.debug("{}: No songs were found with a title similar to {!r}".format(self, title))
                return None, score
            msg = "{}: The song closest to {!r}: {} (score: {})".format(self, title, closest, score)

            if score < 100:
                pat = re.compile("(?P<int>\d+)|(?P<other>\D+)")
                # noinspection PyUnresolvedReferences
                title_nums = "".join(m.groups()[0] for m in iter(pat.scanner(title).match, None) if m.groups()[0])
                # noinspection PyUnresolvedReferences
                album_nums = "".join(m.groups()[0] for m in iter(pat.scanner(closest.file_title).match, None) if m.groups()[0])
                if title_nums != album_nums:
                    log.debug("The numbers in {!r} != the ones in {!r} => score-40".format(title, closest.file_title))
                    score -= 40

            if score < threshold:
                log.debug(msg + " - not being considered a match because score < {}".format(threshold))
                return None, score
            log.debug(msg)
            return closest, score

    def find_song(self, *args, **kwargs):
        return self._find_song(*args, **kwargs)[0]


class CollaborationSong:
    def __init__(self, artist, title, year, collaborators, addl_info):
        self.artist = artist
        self.title = title
        self.year = year
        self.collaborators = collaborators
        self.addl_info = addl_info
        self.file_title = title

    def __repr__(self):
        cls = type(self).__name__
        collabs = "[{}]".format("".join("({})".format(e) for e in self.collaborators)) if self.collaborators else ""
        return "<{}'s {}({!r}){}>".format(self.artist, cls, self.title, collabs)

    def expected_filename(self, ext="mp3"):
        return sanitize("{}.{}".format(self.file_title, ext))


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
        "repackage_album": "Repackage Album"
    }
    numbered_types = (
        "Albums", "Mini Albums", "Special Albums", "Japanese Albums", "Japanese Mini Albums", "Single Albums",
        "Remake Albums", "Repackage Albums"
    )
    multi_disk_types = ("Albums", "Special Albums", "Japanese Albums", "Remake Albums", "Repackage Albums")
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
        self._processed_intro = False
        self._english_name = None
        self._hangul_name = None
        self._name = None

    def __lt__(self, other):
        if isinstance(other, type(self)):
            return (self.artist, self.type, self._num or self.title) < (other.artist, other.type, other._num or other.title)
        raise TypeError("'<' not supported for {!r} < {!r}".format(self, other))

    def __gt__(self, other):
        if isinstance(other, type(self)):
            return (self.artist, self.type, self._num or self.title) > (other.artist, other.type, other._num or other.title)
        raise TypeError("'>' not supported for {!r} > {!r}".format(self, other))

    def __repr__(self):
        return "<{}'s {}({!r})[{}]>".format(self.artist, type(self).__name__, self.title, self.year)

    def __iter__(self):
        yield from sorted(self.tracks)

    def _process_intro(self):
        self._processed_intro = True
        if not self._raw_content:
            self.__is_repackage = False
            return

        nums = []
        num_match = re.search("^(.*) is the (.*)(?:album|single).+by", self._intro.text.strip())
        if num_match:
            alb_name = num_match.group(1)
            try:
                eng, han = map(unsurround, split_name(alb_name))
            except ValueError as e:
                pass
            else:
                self._english_name = eng
                if ";" in han:
                    for val in map(str.strip, han.split(";", 1)):
                        if is_hangul(val):
                            han = val
                            break
                self._hangul_name = han
                if eng and han:
                    self._name = "{} ({})".format(eng, han)
                else:
                    self._name = eng or han

            nums = num_match.group(2).lower().split()
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
            repkg_match = re.search("is a (?:repackage|new edition) of .*?'s? (.*)album", self._raw_content)
            self.__is_repackage = bool(repkg_match)
            if repkg_match:
                nums = repkg_match.group(1).lower().split()

        for i, num in enumerate(nums):
            num = num.strip()
            try:
                self.__num = NUMS[num]  #.get(num, num)
            except KeyError as e:
                # log.error("{}: {!r} is not a number".format(self, num), extra={"red": True})
                if i > 2:
                    raise ValueError("Unable to determine album number for {}".format(self))
            else:
                break

        if self.__is_repackage:
            self.__repackage_name = self.title
            for i, a in enumerate(self._intro.find_all("a")):
                try:
                    href = a.get("href")[6:]
                except TypeError as e:
                    href = None

                if href and (href != self.artist._uri_path):
                    self._repackage_of = self.artist.album_for_uri(href)
                    break

            if not self._repackage_of:
                for album in self.artist:
                    if (album != self) and album.repackage_name == self.title:
                        self._repackage_of = album
                        break

    @cached_property
    def is_repackage(self):
        if not self._processed_intro:
            self._process_intro()
        return self.__is_repackage

    @property
    def repackage_of(self):
        if not self._processed_intro:
            self._process_intro()
        return self._repackage_of

    @cached_property
    def repackage_name(self):
        if not self._processed_intro:
            self._process_intro()
        return self.__repackage_name

    @cached_property
    def is_repkg_double_page(self):
        if not self._processed_intro:
            self._process_intro()
        return self.__repackage_double_page

    @cached_property
    def _num(self):
        if not self._processed_intro:
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
    def expected_dirname(self):
        title = self.title
        if self.type in self.numbered_types:
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
        return os.path.join(self.type, sanitize(title))

    @cached_property
    def expected_rel_path(self):
        artist_dir = self.artist.expected_dirname if hasattr(self.artist, "expected_dirname") else sanitize(self.artist)
        return os.path.join(artist_dir, self.expected_dirname)

    def _tracks_from_wikipedia(self):
        num_strs = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9}
        # If this is using the WikipediaClient, then it's likely for a non-Korean artist
        page_content = self._page_content
        side_bar = page_content.find("table", class_=re.compile("infobox vevent.*"))
        self.title = side_bar.find("th", class_="summary").text     # Collaborations often use song title in link
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

                if not any(i in artist for i in "&,;+"):
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

    def _parse_song(self, ele, song_str, track_num, common_addl_info=None, disk_num=1):
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
                        return Song(artist_obj, self, parsed["name"], parsed["duration"], parsed["extras"], track_num, disk_num=disk_num)

        return Song(self.artist, self, parsed["name"], parsed["duration"], parsed["extras"], track_num, disk_num=disk_num)

    def _tracks(self):
        if isinstance(self._client, WikipediaClient):
            yield from self._tracks_from_wikipedia()
        else:
            if not self._uri_path:
                log.log(9, "No album page exists for {}".format(self))
                return

            page_content = self._page_content
            self._fix_artist(page_content)
            track_list_span = page_content.find("span", id="Track_list") or page_content.find("span", id="Tracklist")
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

                    if self.type in self.multi_disk_types:
                        cd_rx = re.compile("CD\s*(\d+)", re.IGNORECASE)
                        section_header = ol.next_sibling.next_sibling
                        if section_header:
                            m = cd_rx.search(section_header.text)
                            if m:
                                disk_num = int(m.group(1))
                                new_tracks = section_header.next_sibling.next_sibling
                                for track_num, li in enumerate(new_tracks):
                                    yield self._parse_song(li, li.text.strip(), track_num + 1, disk_num=disk_num)

    @cached_property
    def tracks(self):
        return list(self._tracks())

    def _find_track(self, title, threshold=55, track=None):
        closest, score = _find_song(title, [self], track=track)
        if score == 0:
            log.debug("{}: No songs were found with a title similar to {!r}".format(self, title))
            return None, score

        msg = "{}: The song closest to {!r}: {} (score: {})".format(self, title, closest, score)
        if score < threshold:
            log.debug(msg + " - not being considered a match because score < {}".format(threshold))
            return None, score
        log.debug(msg)
        return closest, score

    def find_track(self, *args, **kwargs):
        return self._find_track(*args, **kwargs)[0]
        # attrs = ("file_title", "title", "inverse_han_eng_title")
        # for attr in attrs:
        #     for track in self:
        #         if getattr(track, attr) == title:
        #             return track
        #
        # log.debug("No exact {} track match found for title {!r}, trying lower case...".format(self, title))
        # lc_title = title.lower()
        # for attr in attrs:
        #     for track in self:
        #         if getattr(track, attr).lower() == lc_title:
        #             return track
        #
        # log.debug("No exact {} lower-case track match found for title {!r}, trying languages...".format(self, title))
        # for track in self:
        #     if title in (track.english_title, track.hangul_title):
        #         return track
        # for track in self:
        #     if lc_title == track.english_title.lower():
        #         return track
        #
        # log.debug("No exact {} language-specific lower-case track match found for title {!r}, trying without punctuation...".format(self, title))
        # no_punc = strip_punctuation(lc_title)
        # for track in self:
        #     track_no_punc = strip_punctuation(track.english_title + "".join(track.extras)).lower()
        #     if no_punc == track_no_punc:
        #         return track
        #     # else:
        #     #     log.debug("{!r} != {!r}".format(no_punc, track_no_punc))
        #
        # if track_num:
        #     for track in self:
        #         if track.track == track_num:
        #             return track
        #
        # return None
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
                # log.debug("{} dates: {}".format(self, ", ".join("{!r}".format(s) for s in dates_div.stripped_strings)))
                for s in dates_div.stripped_strings:
                    try:
                        dt = datetime_with_tz(s, "%B %d, %Y")
                    except Exception as e:
                        if last and not dates[last]:
                            dates[last] = s
                        else:
                            m = re.match("^(\S+ \d+, \d{4}) (\(.*\))$", s)
                            if m:
                                dt = datetime_with_tz(m.group(1), "%B %d, %Y")
                                dates[dt] = m.group(2)
                                last = None
                            else:
                                raise ValueError("{}: Unexpected release date value found in: {}".format(self, dates_div))
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

    @cached_property
    def name(self):
        if not self._processed_intro:
            self._process_intro()
        return self._name or self.title

    @cached_property
    def english_name(self):
        if not self._processed_intro:
            self._process_intro()
        return self._english_name

    @cached_property
    def hangul_name(self):
        if not self._processed_intro:
            self._process_intro()
        return self._hangul_name


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

    def expected_filename(self, ext="mp3"):
        if self.track:
            return sanitize("{:02d}. {}.{}".format(self.track, self.file_title, ext))
        return sanitize("{}.{}".format(self.file_title, ext))

    def expected_rel_path(self, ext="mp3"):
        return os.path.join(self.album.expected_rel_path, self.expected_filename(ext))


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
                    if alt.lower() == artist.lower():
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


def sanitize(text):
    return text.translate(PATH_SANITIZATION_TABLE)


def split_name(name):
    """
    :param str name: A song/album/artist title
    :return tuple: (english, hangul)
    """
    name = name.strip()
    if not contains_hangul(name):
        return name, ""
    elif is_hangul(name.translate(NUM_STRIP_TBL)):
        return "", name

    # p_too_many = False
    try:
        parts = ParentheticalParser().parse(name)
    except Exception as e:
        pass
    else:
        if not parts:
            log.debug("ParentheticalParser().parse({!r}) returned nothing".format(name))
        elif len(parts) == 1:     # Not expected to happen
            part = parts[0]
            if not contains_hangul(part):
                return name, ""
            elif is_hangul(part.translate(NUM_STRIP_TBL)):
                return "", part
            else:
                log.debug("ParentheticalParser().parse({!r}) returned only {!r}, and it was mixed".format(name, part))
        elif len(parts) == 2:
            han1, han2 = map(contains_hangul, parts)
            if han1 and han2:
                # raise ValueError("Unable to split {!r} into separate english/hangul strings".format(name))
                pass  # fall back to old method
            elif han1:
                return parts[1], parts[0]
            elif han2:
                return parts[0], parts[1]
        else:
            # p_too_many = True
            # log.debug("ParentheticalParser().parse({!r}) returned too many parts: {}".format(name, parts))
            # traceback.print_stack()
            raise ValueError("Unable to split {!r} into separate english/hangul strings".format(name))

    pat1 = re.compile(r"^([^()[\]]+[([][^()[\]]+[)\]])\s*[([](.*)[)\]]$")   # name (group) [other lang name (group)]
    m = pat1.match(name)
    if m:
        lang1, lang2 = map(str.strip, m.groups())
        han1, han2 = map(contains_hangul, m.groups())
        if han1 and han2:
            raise ValueError("Unable to split {!r} into separate english/hangul strings".format(name))
        elif han1:
            # if p_too_many:
            #     log.debug("ParentheticalParser=>too many; pat1=> eng={!r}, han={!r}".format(lang2, lang1), extra={"color": "yellow"})
            return lang2, lang1
        elif han2:
            # if p_too_many:
            #     log.debug("ParentheticalParser=>too many; pat1=> eng={!r}, han={!r}".format(lang1, lang2), extra={"color": "yellow"})
            return lang1, lang2

    pat2 = re.compile(r"^(.*)\s*[([](.*)[)\]]$")  # name (other lang name)
    m = pat2.match(name)
    if m:
        lang1, lang2 = map(str.strip, m.groups())
        han1, han2 = map(contains_hangul, m.groups())
        if han1 and han2:
            raise ValueError("Unable to split {!r} into separate english/hangul strings".format(name))
        elif han1:
            # if p_too_many:
            #     log.debug("ParentheticalParser=>too many; pat2=> eng={!r}, han={!r}".format(lang2, lang1), extra={"color": "yellow"})
            return lang2, lang1
        elif han2:
            # if p_too_many:
            #     log.debug("ParentheticalParser=>too many; pat2=> eng={!r}, han={!r}".format(lang1, lang2), extra={"color": "yellow"})
            return lang1, lang2

    raise ValueError("Unable to split {!r} into separate english/hangul strings".format(name))


def eng_name(obj, name, attr):
    pat = re.compile("(.*)\s*\((.*)\)")
    m = pat.match(name)
    if m:
        eng, han = map(str.strip, m.groups())
        if contains_hangul(eng):
            if contains_hangul(han):
                raise AttributeError("{} Does not have an {}".format(obj, attr))
            m = pat.match(eng)
            if m:                                       # Use case: 'soloist (as hangul) (group name)'
                eng, han = map(str.strip, m.groups())
                if contains_hangul(eng):
                    if contains_hangul(han):
                        raise AttributeError("{} Does not have an {}".format(obj, attr))
                    return han
                return eng
            return han
        return eng
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


def _normalize_title(title):
    return re.sub("\s+", " ", fuzz_utils.full_process(title, force_ascii=False))


def wiki_obj_match_scorer(title, obj, track=None):
    if isinstance(obj, Song):
        attrs = ("title", "file_title", "english_title", "hangul_title", "inverse_han_eng_title")
        full_title_attr = "file_title"
        scorer = fuzz.token_sort_ratio
    elif isinstance(obj, CollaborationSong):
        attrs = ("title",)
        full_title_attr = "title"
        scorer = fuzz.token_sort_ratio
    elif isinstance(obj, Album):
        attrs = ("title", "name", "english_name", "hangul_name")
        full_title_attr = None
        scorer = fuzz.WRatio
    else:
        raise TypeError("Unexpected type {!r} for {}".format(type(obj).__name__, obj))

    pat = re.compile(r"(?P<int>\d+)|(?P<other>\D+)")
    # noinspection PyUnresolvedReferences
    title_nums = "".join(m.groups()[0] for m in iter(pat.scanner(title).match, None) if m.groups()[0])

    best_score = 0
    best_attr = None
    score_mod = 0
    for attr in attrs:
        if best_score >= 100:
            break

        raw_val = getattr(obj, attr) or ""
        val = _normalize_title(raw_val)
        if not val:
            continue
        score = scorer(title, val, force_ascii=False, full_process=False)
        # log.debug("{} =?= {} [{}] => {}".format(title, val, attr, score))
        # noinspection PyUnresolvedReferences
        val_nums = "".join(m.groups()[0] for m in iter(pat.scanner(val).match, None) if m.groups()[0])
        if val_nums != title_nums:
            score -= 40

        if score > best_score:
            best_score = score
            best_attr = attr
        if attr == full_title_attr:
            if ("live" in title and "live" not in val) or ("live" in val and "live" not in title):
                score_mod -= 25
        if attr == "file_title":
            try:
                eng, han = split_name(raw_val)
            except Exception as e:
                pass
            else:
                for lang_val in (eng, han):
                    val = _normalize_title(lang_val)
                    if not val:
                        continue
                    score = scorer(title, val, force_ascii=False, full_process=False)
                    if score > best_score:
                        best_score = score
                        best_attr = attr

    if track is not None:
        other_track = getattr(obj, "track", None)
        if other_track is not None:
            other_track = str(other_track)
            if track != other_track:
                score_mod -= 50
            else:
                score_mod += 15

    # log.debug("{} =?= {} [{}] => {}".format(title, obj, best_attr, best_score + score_mod), extra={"color": "green"})
    return best_score + score_mod, best_attr


def process_wiki_obj_match(title, objs, track=None, score_cutoff=0):
    try:
        if objs is None or len(objs) == 0:
            raise StopIteration
    except TypeError:
        pass

    def processor(text):
        return re.sub("\s+", " ", fuzz_utils.full_process(text, force_ascii=False))

    # Run the processor on the input query.
    processed_query = processor(title)
    if len(processed_query) == 0:
        log.warning("Processor reduced query to empty string - all comparisons will score 0 [orig: {!r}]".format(title))
        raise StopIteration

    for obj in objs:
        score, best_attr = wiki_obj_match_scorer(processed_query, obj, track)
        if score >= score_cutoff:
            yield (score, obj, best_attr)


def find_best_wiki_obj_match(title, objs, track=None):
    best_list = list(process_wiki_obj_match(title, objs, track))
    # log.debug("{} =?= {} =>\n{}".format(title, objs, "\n".join("   - {}".format(l) for l in best_list)), extra={"color": "green"})
    try:
        max_row = max(best_list, key=lambda row: row[0])
        # log.debug("==>> {}".format(max_row), extra={"color": "red"})
        return max_row
    except ValueError as e:
        log.debug("Encountered ValueError while processing {}: {}".format(title, e))
        return 0, None, None


def _find_album(title, albums, try_split=True):
    best_score, best_album = 0, None
    score, album, attr = find_best_wiki_obj_match(title, albums)
    log.debug("Best match for album {!r} based on {!r}: {} ({})".format(title, attr, album, score))
    if score >= 100:
        return album, score
    else:
        if score > best_score:
            best_score = score
            best_album = album

    if (best_score <= 70) and try_split:
        try:
            eng, han = split_name(title)
        except ValueError as e:
            pass
        else:
            for lang in (eng, han):
                if lang:
                    lang_album, lang_score = _find_album(lang, albums, False)
                    if lang_score > best_score:
                        best_score = lang_score
                        best_album = lang_album
    return best_album, best_score


def _find_song(title, albums, features=None, try_split=True, track=None):
    """
    :param str title: The string for which the closest match should be found
    :param iterable albums: Iterable that yields :class:`Album` instances
    :param iterable|None features: Feature tracks
    :param track: Track number, if known
    :return tuple: (Song|CollaborationSong, int|float)
    """
    best_score, best_song = 0, None
    songs = [song for album in albums for song in album]
    if songs:
        score, song, attr = find_best_wiki_obj_match(title, songs, track)
        log.debug("Best match for song {!r} based on {!r}: {} ({})".format(title, attr, song, score))
        if score >= 100:
            return song, score
        else:
            if score > best_score:
                best_score = score
                best_song = song

    if features:
        songs = {s: s.title for s in features}
        if songs:
            score, song, attr = find_best_wiki_obj_match(title, features, track)
            log.debug("Best match for {!r} based on {!r}: {} ({})".format(title, attr, song, score))
            if score >= 100:
                return song, score
            else:
                if score > best_score:
                    best_score = score
                    best_song = song

    if (best_score <= 70) and try_split:
        try:
            eng, han = split_name(title)
        except ValueError as e:
            pass
        else:
            for lang in (eng, han):
                if lang:
                    lang_song, lang_score = _find_song(lang, albums, features, False, track)
                    if lang_score > best_score:
                        best_score = lang_score
                        best_song = lang_song
    return best_song, best_score


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
