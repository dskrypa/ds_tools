#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
:author: Doug Skrypa
"""

import logging
import re
import types
from collections import OrderedDict
from enum import Enum
from itertools import chain, combinations
from urllib.parse import urlparse

# import Levenshtein as lev
from bs4.element import NavigableString
from fuzzywuzzy import utils as fuzz_utils

from ..utils import (
    RecursiveDescentParser, UnexpectedTokenError, is_any_cjk, ParentheticalParser, contains_any_cjk, is_hangul,
    datetime_with_tz, DASH_CHARS, QMARKS, num_suffix
)
from .exceptions import *

__all__ = [
    "SongTitleParser", "DiscographyEntryParser", "sanitize", "unsurround", "_normalize_title", "parse_intro_name",
    "split_name", "eng_cjk_sort", "categorize_langs", "LangCat", "parse_discography_entry", "parse_aside",
    "parse_album_page", "parse_track_info", "parse_ost_page", "parse_wikipedia_album_page", "parse_infobox",
    "edition_combinations", "multi_lang_name", "comparison_type_check"
]
log = logging.getLogger("ds_tools.music.utils")

NUM_STRIP_TBL = str.maketrans({c: "" for c in "0123456789"})
NUM2INT = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9}
NUMS = {
    "first": "1st", "second": "2nd", "third": "3rd", "fourth": "4th", "fifth": "5th", "sixth": "6th",
    "seventh": "7th", "eighth": "8th", "ninth": "9th", "tenth": "10th", "debut": "1st"
}
PATH_SANITIZATION_DICT = {c: "" for c in "*;?<>\""}
PATH_SANITIZATION_DICT.update({"/": "_", ":": "-", "\\": "_", "|": "-"})
PATH_SANITIZATION_TABLE = str.maketrans(PATH_SANITIZATION_DICT)
QMARK_STRIP_TBL = str.maketrans({c: "" for c in QMARKS})


class SongTitleParser(RecursiveDescentParser):
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


class DiscographyEntryParser(SongTitleParser):
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


def sanitize(text):
    return text.translate(PATH_SANITIZATION_TABLE)


def unsurround(a_str, *chars):
    chars = chars or (("\"", "\""), ("(", ")"), ("“", "“"))
    for a, b in chars:
        if a_str.startswith(a) and a_str.endswith(b):
            a_str = a_str[1:-1].strip()
    return a_str


def _normalize_title(title):
    return re.sub("\s+", " ", fuzz_utils.full_process(title, force_ascii=False))


def parse_intro_name(text):
    first_sentence = text.strip().partition(". ")[0].strip()  # Note: space is intentional
    parser = ParentheticalParser()
    try:
        parts = parser.parse(first_sentence)    # Note: returned strs already stripped of leading/trailing spaces
    except Exception as e:
        raise ValueError("Unable to parse artist name from intro: {}".format(first_sentence)) from e

    if len(parts) == 1:
        base, details = parts[0], ""
    else:
        base, details = parts[:2]
    if " is " in base:
        base = base[:base.index(" is ")].strip()
        eng, cjk = eng_cjk_sort(base)
        return eng, cjk, None, None
    elif is_any_cjk(details):
        return base, details, None, None
    elif not contains_any_cjk(details):
        eng, cjk = eng_cjk_sort(base)
        return eng, cjk, None, None

    cjk = ""
    found_hangul = False
    stylized = None
    aka = None
    aka_leads = ("aka", "a.k.a.", "also known as", "or simply")
    for part in map(str.strip, re.split("[;,]", details)):
        lc_part = part.lower()
        if lc_part.startswith("stylized as"):
            stylized = part[11:].strip()
        elif is_any_cjk(part) and not found_hangul:
            found_hangul = is_hangul(part)
            cjk = part
        elif ":" in part and not found_hangul:
            _lang_name, cjk = eng_cjk_sort(tuple(map(str.strip, part.split(":", 1))))
            found_hangul = is_hangul(cjk)
        elif not aka:
            for lead in aka_leads:
                if lc_part.startswith(lead):
                    aka = part[len(lead):].strip()
                    break

    return base, cjk, stylized, aka


def split_name(name, unused=False, check_keywords=True):
    """
    :param str name: A song/album/artist title
    :param bool unused: Return a 3-tuple instead of a 2-tuple, with the 3rd element being the content that was discarded
    :param bool check_keywords: Check for some key words at the start of the English name, such as 'inst.' or 'feat.'
      and count that as an invalid English name part
    :return tuple: (english, cjk)
    """
    name = name.strip()
    parser = ParentheticalParser()
    try:
        parts = parser.parse(name)   # Note: returned strs already stripped of leading/trailing spaces
    except Exception as e:
        raise ValueError("Unable to split {!r} into separate English/CJK strings".format(name)) from e

    if not parts:
        raise ValueError("Unable to split {!r} into separate English/CJK strings (nothing was parsed)".format(name))

    eng, cjk, not_used = None, None, None
    langs = categorize_langs(parts)
    s = "s" if len(parts) > 1 else ""
    log.log(9, "ParentheticalParser().parse({!r}) => {} part{}: {} ({})".format(name, len(parts), s, parts, langs))
    if len(parts) == 1:
        try:
            eng, cjk = eng_cjk_sort(parts[0], langs[0])
        except ValueError as e:
            raise ValueError("Unable to split {!r} into separate English/CJK strings".format(name)) from e
    elif len(parts) == 2:
        if LangCat.MIX not in langs and len(set(langs)) == 2:
            eng, cjk = eng_cjk_sort(parts, langs)           # Name (other lang)
        elif langs[0] == LangCat.MIX and langs[1] != LangCat.MIX and has_parens(parts[0]):
            eng, cjk = split_name(parts[0])                 # Soloist (other lang) (Group single lang)
            not_used = parts[1]
        elif langs[0] != LangCat.MIX and langs[1] == LangCat.MIX and has_parens(parts[1]):
            eng, cjk = eng_cjk_sort(parts[0], langs[0])     # Soloist single lang (Group (group other lang))
            try:
                not_used = split_name(parts[1])
            except Exception:
                not_used = parts[1]
        elif langs == (LangCat.MIX, LangCat.MIX) and all(has_parens(p) for p in parts):
            eng, cjk = split_name(parts[0])                 # Soloist (other lang) [Group (group other lang)]
            try:
                not_used = split_name(parts[1])
            except Exception:
                not_used = parts[1]
    elif len(parts) == 3:
        if LangCat.MIX not in langs and len(set(langs)) == 2:
            if langs[0] == langs[1] != langs[2]:
                try:
                    soloist_b, group_b = parser.parse(parts[2])
                except ValueError:  # Not enough values to unpack => no parens, or they weren't followed by whitespace
                    eng, cjk = eng_cjk_sort(parts[0], langs[0])         # Soloist (group) (group other lang)
                    not_used = parts[1:]
                else:
                    soloist_a, group_a = parts[:2]          # Soloist (group) (soloist other lang (group other lang))
                    eng, cjk = eng_cjk_sort((soloist_a, soloist_b), langs[1:])
                    not_used = eng_cjk_sort((group_a, group_b), langs[1:])
            else:
                eng, cjk = eng_cjk_sort(parts[:2], langs[:2])           # Name (other lang) (Group|extra single lang)
                not_used = parts[2]

    if not eng and not cjk:
        # traceback.print_stack()
        raise ValueError("Unable to split {!r} into separate English/CJK strings".format(name))

    if check_keywords and eng.lower().startswith(("feat.", "featuring", "inst.", "instrumental")):
        log.debug("Shuffling return values due to keywords: {}".format((eng, cjk, not_used)))
        if not_used is None:
            not_used = eng
        elif isinstance(not_used, str):
            not_used = [not_used, eng]
        else:
            not_used = list(not_used)
            not_used.append(eng)
        eng = ""
        if not cjk:
            raise ValueError("Unable to split {!r} into separate English/CJK strings".format(name))

    return (eng, cjk, not_used) if unused else (eng, cjk)


def eng_cjk_sort(strs, langs=None, permissive=False):
    """
    :param str|tuple|list|iterator strs: A single string or a tuple/list with 2 elements
    :param LangCat|tuple|None langs: A single Langs value or a 2-tuple of Langs (ENG/CJK only) or None
    :param bool permissive: Allow a 2-tuple of english and mixed rather than requiring no english in the second str
    :return tuple: (str(eng), str(cjk))
    """
    # noinspection PyTypeChecker
    if isinstance(strs, (types.GeneratorType, map)):
        strs = list(strs)
    if langs is None:
        langs = categorize_langs([strs] if isinstance(strs, str) else strs)
        if isinstance(strs, str):
            langs = langs[0]
    if not isinstance(strs, str) and len(strs) == 1:
        langs = langs[0]
        strs = strs[0]
    if langs == (LangCat.ENG, LangCat.CJK) or (permissive and langs == (LangCat.ENG, LangCat.MIX)):
        return strs
    elif langs == (LangCat.CJK, LangCat.ENG) or (permissive and langs == (LangCat.MIX, LangCat.ENG)):
        return reversed(strs)
    elif isinstance(strs, str):
        if langs == LangCat.ENG:
            return strs, ""
        elif langs == LangCat.CJK:
            return "", strs
    raise ValueError("Unexpected values: strs={!r}, langs={!r}".format(strs, langs))


def has_parens(text):
    return any(c in text for c in "()[]")


class LangCat(Enum):
    ENG = 1
    CJK = 2
    MIX = 3


def categorize_langs(strs):
    return tuple(LangCat.CJK if is_any_cjk(s) else LangCat.MIX if contains_any_cjk(s) else LangCat.ENG for s in strs)


def parse_discography_entry(artist, ele, album_type, lang, type_idx):
    ele_text = ele.text.strip()
    try:
        parsed = ParentheticalParser().parse(ele_text)
    except Exception as e:
        log.warning("Unhandled discography entry format {!r} for {}".format(ele_text, artist), extra={"red": True})
        return None
    # else:
    #     log.debug("Parsed {!r} => {}".format(ele_text, parsed))

    links = [
        (t, h[6:] if h.startswith("/wiki/") else h)
        for t, h in ((a.text, a.get("href") or "") for a in ele.find_all("a"))
    ]
    base_type = album_type and (album_type[:-2] if re.search(r"_\d$", album_type) else album_type).lower() or ""
    if base_type == "features" and parsed[0].endswith("-"):
        primary_artist = parsed.pop(0)[:-1].strip()
        primary_uri = links[0][1] if links and links[0][0] == primary_artist else None
        log.debug("Primary artist={}, links[0]={}".format(primary_artist, links[0]))
    else:
        primary_artist = artist.english_name
        primary_uri = artist._uri_path
    year = int(parsed.pop()) if len(parsed[-1]) == 4 and parsed[-1].isdigit() else None
    title = parsed.pop(0)
    collabs, misc_info = {}, []
    for item in parsed:
        if item.lower().startswith(("with ", "feat. ", "feat ", "as ")):
            item = item.split(maxsplit=1)[1]    # remove the with/feat prefix
            item_collabs = set(str2list(item))
            if links:
                collabs.update({text: href for text, href in links if text in item_collabs})
            else:
                collabs.update({name: None for name in item_collabs})
        else:
            misc_info.append(item)

    if artist.english_name not in collabs or artist._uri_path not in collabs.values():
        if primary_artist != artist.english_name:
            collabs[artist.english_name] = artist._uri_path

    is_feature_or_collab = base_type in ("features", "collaborations")
    is_ost = base_type in ("ost", "osts")

    non_artist_links = [lnk for lnk in links if lnk[1] and lnk[1] != primary_uri and lnk[1] not in collabs.values()]
    if non_artist_links:
        if len(non_artist_links) > 1:
            fmt = "Too many non-artist links found: {}\nFrom li: {}\nParsed parts: {}"
            raise WikiEntityParseException(fmt.format(non_artist_links, ele, parsed))

        link_text, link_href = non_artist_links[0]
        if title != link_text and not is_feature_or_collab:
            # if is_feature_or_collab: likely a feature / single with a link to a collaborator
            if not any(title.replace("(", c).replace(")", c) == link_text for c in "-~"):
                log.debug("Unexpected first link text {!r} for album {!r}".format(link_text, title))

        if link_href.startswith(("http://", "https://")):
            url = urlparse(link_href)
            if url.hostname == "en.wikipedia.org":
                uri_path = url.path[6:]
                wiki = "en.wikipedia.org"
                # Probably a collaboration song, so title is likely a song and not the album title
            else:
                log.debug("Found link from {}'s discography to unexpected site: {}".format(artist, link_href))
                uri_path = None
                wiki = "kpop.fandom.com"
        else:
            uri_path = link_href or None
            wiki = "kpop.fandom.com"
    else:
        if is_ost:
            m = re.match("(.*? OST).*", title)
            if m:
                non_part_title = m.group(1).strip()
                uri_path = non_part_title.replace(" ", "_")
            else:
                uri_path = title.replace(" ", "_")
            wiki = "wiki.d-addicts.com"
        elif is_feature_or_collab:
            uri_path = None
            wiki = "kpop.fandom.com"
            # Probably a collaboration song, so title is likely a song and not the album title
        else:
            uri_path = None
            wiki = "kpop.fandom.com"
            # May be an album without a link, or a repackage detailed on the same page as the original

    info = {
        "title": title, "primary_artist": (primary_artist, primary_uri), "type": album_type, "base_type": base_type,
        "year": year, "collaborators": collabs, "misc_info": misc_info, "language": lang, "uri_path": uri_path,
        "wiki": wiki, "is_feature_or_collab": is_feature_or_collab, "is_ost": is_ost,
        "num": "{}{}".format(type_idx, num_suffix(type_idx))
    }
    return info


def str2list(text, pat="(?: and |,|;|&)"):
    """Convert a string list to a proper list"""
    return list(map(str.strip, re.split(pat, text)))


def parse_aside(aside):
    """
    Parse the 'aside' element from a wiki page into a more easily used data format

    :param aside: Beautiful soup 'aside' element
    :return dict: The parsed data
    """
    unexpected_date_fmt = "Unexpected release date format in: {}"
    parsed = {}
    for ele in aside.children:
        tag_type = ele.name
        if isinstance(ele, NavigableString) or tag_type in ("figure", "section"):    # newline/image/footer
            continue

        key = ele.get("data-source")
        if not key or key == "image":
            continue
        elif tag_type == "h2":
            value = ele.text
        else:
            val_ele = list(ele.children)[-1]
            if isinstance(val_ele, NavigableString):
                val_ele = val_ele.previous_sibling

            if key == "released":
                value = []
                for s in val_ele.stripped_strings:
                    try:
                        dt = datetime_with_tz(s, "%B %d, %Y")       # KPop wiki
                    except Exception as e:
                        try:
                            dt = datetime_with_tz(s, "%d %B %Y")    # Wikipedia
                        except Exception as e0:
                            if value and not value[-1][1]:
                                value[-1] = (value[-1][0], unsurround(s))
                            else:
                                m = re.match("^(\S+ \d+, \d{4})\s*\((.*)\)$", s)
                                if m:
                                    try:
                                        dt = datetime_with_tz(m.group(1), "%B %d, %Y")
                                    except Exception as e1:
                                        raise ValueError(unexpected_date_fmt.format(val_ele)) from e1
                                    else:
                                        value.append((dt, m.group(2)))
                                else:
                                    raise ValueError(unexpected_date_fmt.format(val_ele))
                        else:
                            value.append((dt, None))
                    else:
                        value.append((dt, None))
            elif key == "length":
                value = []
                for s in val_ele.stripped_strings:
                    if re.match("^\d*:?\d+:\d{2}$", s):
                        value.append((s, None))
                    else:
                        m = re.match("^(\d*:?\d+:\d{2})\s*\((.*)\)$", s)
                        if m:
                            value.append(tuple(m.groups()))
                        elif not value[-1][1]:
                            value[-1] = (value[-1][0], unsurround(s))
                        else:
                            raise ValueError("Unexpected length format in: {}".format(val_ele))
            elif key in ("agency", "artist", "associated", "composer", "current", "label", "writer"):
                anchors = list(val_ele.find_all("a"))
                if anchors:
                    value = {a.text: a.get("href") for a in anchors}
                else:
                    ele_children = list(val_ele.children)
                    if not isinstance(ele_children[0], NavigableString) and ele_children[0].name == "ul":
                        value = {li.text: None for li in ele_children[0].find_all("li")}
                    else:
                        value = {name: None for name in str2list(val_ele.text)}
            elif key in ("format", ):
                ele_children = list(val_ele.children)
                if not isinstance(ele_children[0], NavigableString) and ele_children[0].name == "ul":
                    value = [li.text for li in ele_children[0].find_all("li")]
                else:
                    value = str2list(val_ele.text)
            else:
                value = val_ele.text
        parsed[key] = value
    return parsed


def _album_num_type(details):
    alb_broad_type = next((val for val in ("album", "single") if val in details), None)
    if alb_broad_type:
        alb_type_desc = details[:details.index(alb_broad_type) + 1]
        if "full-length" in alb_type_desc:
            alb_type_desc.remove("full-length")
        num = NUMS.get(alb_type_desc[0])
        return num, " ".join(alb_type_desc[1:] if num else alb_type_desc)
    raise ValueError("Unable to determine album type")


def _first_side_info_val(side_info, key):
    try:
        return side_info.get(key, [])[0][0]
    except IndexError:
        return None


def parse_album_page(uri_path, clean_soup, side_info):
    """
    :param clean_soup: The :attr:`WikiEntity._clean_soup` value for an album
    :param dict side_info: Parsed 'aside' element contents
    :return list: List of dicts representing the albums found on the given page
    """
    bad_intro_fmt = "Unexpected album intro sentence format in {}: {!r}"
    album0 = {}
    album1 = {}
    intro_text = clean_soup.text.strip()
    intro_match = re.match("^(.*?)\s+is\s+(?:a|the)\s+(.*?)\.\s", intro_text)
    if not intro_match:
        raise WikiEntityParseException(bad_intro_fmt.format(uri_path, intro_text[:200]))

    album0["title_parts"] = parse_intro_name(intro_match.group(1))  # base, cjk, stylized, aka

    details_str = intro_match.group(2)
    details_str.replace("full length", "full-length")
    details = list(details_str.split())
    if (details[0] == "repackage") or (details[0] == "new" and details[1] == "edition"):
        album0["repackage"] = True
        for i, ele in enumerate(details):
            if ele.endswith("'s"):
                artist_idx = i
                break
        else:
            raise WikiEntityParseException(bad_intro_fmt.format(uri_path, intro_text[:200]))

        try:
            album0["num"], album0["type"] = _album_num_type(details[artist_idx:])
        except ValueError:
            raise WikiEntityParseException(bad_intro_fmt.format(uri_path, intro_text[:200]))

        for a in clean_soup.find_all("a"):
            if details_str.endswith(a.text):
                href = a.get("href")
                if href:
                    album0["repackage_of_href"] = href[6:]
                    album0["repackage_of_title"] = a.text
                break
        else:
            raise WikiEntityParseException("Unable to find link to repackaged version of {}".format(uri_path))
    elif (details[0] == "original" and details[1] == "soundtrack") or (details[0].lower() in ("ost", "soundtrack")):
        album0["num"] = None
        album0["type"] = "OST"
        album0["repackage"] = False
    else:
        album0["repackage"] = False
        try:
            album0["num"], album0["type"] = _album_num_type(details)
        except ValueError:
            if details_str.startswith("song by"):
                album0["num"], album0["type"] = None, "single"
            else:
                raise WikiEntityParseException(bad_intro_fmt.format(uri_path, intro_text[:200]))

        repkg_match = re.search("A repackage titled (.*) (?:was|will be) released", intro_text)
        if repkg_match:
            repkg_title = repkg_match.group(1)
            repkg_dt = next((dt for dt, note in side_info.get("released", []) if note == "repackage"), None)
            if repkg_dt:
                album1["title_parts"] = parse_intro_name(repkg_title)   # base, cjk, stylized, aka
                album1["length"] = next((val for val, note in side_info.get("length", []) if note == "repackage"), None)
                album1["num"] = album0["num"]
                album1["type"] = album0["type"]
                album1["repackage"] = True
                album1["repackage_of_href"] = uri_path
                album1["repackage_of_title"] = repkg_title
                album0["repackage_href"] = uri_path
                album0["repackage_title"] = repkg_title
                album1["released"] = repkg_dt
                album1["links"] = []
            else:
                for a in clean_soup.find_all("a"):
                    if a.text == repkg_title:
                        href = a.get("href")
                        if href:
                            album0["repackage_href"] = href[6:]
                            album0["repackage_title"] = repkg_title
                        break
                else:
                    raise WikiEntityParseException("Unable to find link to repackaged version of {}".format(uri_path))

    links = []
    for ele in clean_soup.children:
        if isinstance(ele, NavigableString):
            continue
        elif ele.name in ("h1", "h2", "h3", "h4"):
            break
        links.extend((a.text, a.get("href")) for a in ele.find_all("a"))
    album0["links"] = links
    album0["released"] = _first_side_info_val(side_info, "released")
    album0["length"] = _first_side_info_val(side_info, "length")
    album0["name"] = side_info.get("name")

    albums = [album0, album1] if album1 else [album0]
    for album in albums:
        album["artists"] = side_info.get("artist", {})

    try:
        track_lists = parse_album_tracks(uri_path, clean_soup)
    except NoTrackListException as e:
        if not album1 and "single" in album0["type"].lower():
            eng, cjk = album0["title_parts"][:2]
            album0["tracks"] = {
                "section": None, "tracks": [{"name_parts": (eng, cjk), "num": 1, "length": album0["length"] or "-1:00"}]
            }
        else:
            raise e
    else:
        if album1:
            if len(track_lists) != 2:
                err_msg = "Unexpected track section count for original+repackage combined page {}".format(uri_path)
                raise WikiEntityParseException(err_msg)
            for i, album in enumerate(albums):
                album["tracks"] = track_lists[i]
        else:
            if len(track_lists) == 1:
                album0["tracks"] = track_lists[0]
            else:
                album0["track_lists"] = track_lists

    return albums


def parse_album_tracks(uri_path, clean_soup):
    track_list_span = clean_soup.find("span", id="Track_list") or clean_soup.find("span", id="Tracklist")
    if not track_list_span:
        raise NoTrackListException("Unable to find track list for album {}".format(uri_path))

    h2 = track_list_span.find_parent("h2")
    if not h2:
        raise WikiEntityParseException("Unable to find track list header for album {}".format(uri_path))

    disk_rx = re.compile(r"^Dis[ck]\s+(\S+)\s*[{}]?\s*(.*)$".format(DASH_CHARS + ":"), re.IGNORECASE)
    unexpected_num_fmt = "Unexpected disk number format for {}: {!r}"
    parser = ParentheticalParser(False)
    track_lists = []
    section, links, disk = None, [], 1
    for ele in h2.next_siblings:
        if isinstance(ele, NavigableString):
            continue

        ele_name = ele.name
        if ele_name == "h2":
            break
        elif ele_name in ("ol", "ul"):
            if section and (section if isinstance(section, str) else section[0]).lower().startswith("dvd"):
                section, links = None, []
                continue

            tracks = []
            for i, li in enumerate(ele.find_all("li")):
                track = parse_track_info(i + 1, li.text, uri_path)
                track_links = [(a.text, a.get("href")) for a in li.find_all("a")]
                if track_links:
                    track["links"] = track_links
                tracks.append(track)

            track_lists.append({"section": section, "tracks": tracks, "links": links, "disk": disk})
            section, links = None, []
        else:
            for junk in ele.find_all(class_="editsection"):
                junk.extract()
            section = ele.text
            links = [(a.text, a.get("href")) for a in ele.find_all("a")]
            if has_parens(section):
                try:
                    section = parser.parse(section)
                except Exception as e:
                    pass

            disk_section = section if not section or isinstance(section, str) else section[0]
            if disk_section and disk_section.lower().startswith(("disk", "disc")):
                m = disk_rx.match(disk_section)
                if not m:
                    raise WikiEntityParseException(unexpected_num_fmt.format(uri_path, disk_section))
                try:
                    disk = NUM2INT[m.group(1).lower()]
                except KeyError as e:
                    raise WikiEntityParseException(unexpected_num_fmt.format(uri_path, m.group(1))) from e
                disk_section = m.group(2).strip() or None
                if isinstance(section, str):
                    section = disk_section
                else:
                    section[0] = disk_section
            else:
                disk = 1

    return track_lists


def _combine_name_parts(name_parts):
    langs = categorize_langs(name_parts)
    last = None
    for i, lang in enumerate(langs):
        if lang == last:
            prefix = name_parts[:i-1]
            suffix = name_parts[i+1:]
            combined = "{} ({})".format(*name_parts[i-1:i+1])
            return prefix + [combined] + suffix
        last = lang
    combined = "{} ({})".format(*name_parts[:2])
    return [combined] + name_parts[2:]


def parse_track_info(idx, text, source, length=None):
    """
    :param int|str idx: Track number / index in list (1-based)
    :param str text: The text to be parsed
    :param str source: uri_path or other identifier for the source of the text being parsed (to add context to errors)
    :param str|None length: Length of the track, if known (MM:SS format)
    :return dict: The parsed track information
    """
    text = unsurround(text.strip(), *(c*2 for c in QMARKS))
    if isinstance(idx, str):
        idx = idx.strip()
        if idx.endswith("."):
            idx = idx[:-1]
        try:
            idx = int(idx)
        except ValueError as e:
            fmt = "Error parsing track number {!r} for {!r} from {}: {}"
            raise TrackInfoParseException(fmt.format(idx, text, source, e)) from e

    track = {"num": idx, "length": "-1:00"}
    parser = ParentheticalParser(False)
    try:
        parsed = parser.parse(text)
    except Exception as e:
        raise TrackInfoParseException("Error parsing track from {}: {!r}".format(source, text)) from e

    # log.debug("{!r} => {}".format(text, parsed))
    if length:
        track["length"] = length

    if has_parens(parsed[0]):   #.count("(") > 1:
        to_re_parse = parsed.pop(0)
        _parsed = parsed
        try:
            parsed = parser.parse(to_re_parse)
        except Exception as e:
            raise TrackInfoParseException("Error parsing track from {}: {!r}".format(source, parsed[0])) from e
        parsed.extend(_parsed)

    name_parts, collabs, misc = [], [], []
    for n, part in enumerate(parsed):
        if n == 0:
            name_parts.append(part)
            continue

        lc_part = part.lower()
        feat = next((val for val in ("with", "feat.", "feat ", "featuring") if val in lc_part), None)
        if feat:
            collab_part = part[len(feat):].strip() if lc_part.startswith(feat) else part
            collabs.extend(str2list(collab_part, pat="(?: and |,|;|&| feat\.? | featuring | with )"))
            # collabs.extend(str2list(part[len(feat):].strip()))
        elif lc_part.endswith((" ver.", " ver", " version")):
            value = part.rsplit(maxsplit=1)[0]
            if lc_part.startswith(("inst", "acoustic")):
                track["version"] = value
            else:
                track["language"] = {"kr": "Korean", "jp": "Japanese"}.get(value.lower(), value)
        elif lc_part.startswith(("inst", "acoustic")):
            track["version"] = part
        elif any(val in lc_part for val in ("bonus", " ost", " mix", "remix", "edition only")):  # spaces intentional
            misc.append(part)
        elif any(lc_part.startswith(c) for c in DASH_CHARS):
            try:
                len_rx = parse_track_info._len_rx
            except AttributeError:
                len_rx = parse_track_info._len_rx = re.compile(r"^[{}]\s*(\d+:\d{{2}})$".format(DASH_CHARS))

            m = len_rx.match(part)
            if m:
                track["length"] = m.group(1)
        else:
            name_parts.append(part)

    if len(name_parts) > 2:
        log.debug("High name part count in {} [{!r} =>]: {}".format(source, text, name_parts))
        while len(name_parts) > 2:
            name_parts = _combine_name_parts(name_parts)

    try:
        track["name_parts"] = eng_cjk_sort(name_parts[0] if len(name_parts) == 1 else name_parts)
    except ValueError:
        track["name_parts"] = tuple(name_parts) if len(name_parts) == 2 else (name_parts[0], "")

    if collabs:
        track["collaborators"] = sorted(collabs)
    if misc:
        track["misc"] = misc

    return track


def parse_ost_page(uri_path, clean_soup):
    first_h2 = clean_soup.find("h2")
    if not first_h2:
        raise WikiEntityParseException("Unable to find first OST part section in {}".format(uri_path))

    track_lists = []
    h2 = first_h2
    while True:
        # log.debug("Processing section: {}".format(h2))
        if not h2 or h2.next_element.get("id", "").lower() == "see_also":
            break

        section = h2.text
        info_ul = h2.find_next_sibling("ul")
        if not info_ul:
            break
        info = {}
        for i, li in enumerate(info_ul.find_all("li")):
            try:
                key, value = map(str.strip, li.text.strip().split(":", 1))
            except ValueError as e:
                fmt = "Error splitting key:value pair {!r} from {}: {}"
                raise WikiEntityParseException(fmt.format(li.text.strip(), uri_path, e)) from e
            key = key.lower()
            if i == 0 and key != "title":
                return track_lists
            elif key == "title":
                try:
                    value = eng_cjk_sort(map(str.strip, value.split("/")), permissive=True)
                except Exception as e:
                    pass
            elif key == "release date":
                try:
                    value = datetime_with_tz(value, "%Y-%b-%d")
                except Exception as e:
                    log.debug("Error parsing release date {!r} for {}: {}".format(value, uri_path, e))
                    pass
            elif key == "language":
                value = str2list(value)
            elif key == "artist":
                artists = str2list(value, pat="(?: and |,|;|&| feat\.? )")
                value = []
                for artist in artists:
                    try:
                        soloist, of_group = artist.split(" of ")
                    except Exception as e:
                        value.append({"artist": split_name(artist)})
                    else:
                        value.append({"artist": split_name(soloist), "of_group": split_name(of_group)})

            info[key] = value

        tracks = []
        track_table = info_ul.find_next_sibling("table")
        for tr in track_table.find_all("tr"):
            tds = tr.find_all("td")
            if tds:
                track_name = eng_cjk_sort(tds[1].stripped_strings, permissive=True)
                if all(part.lower().endswith("(inst.)") for part in track_name):
                    track_name = "{} ({}) (Inst.)".format(*(part[:-7].strip() for part in track_name))
                else:
                    track_name = "{} ({})".format(*track_name)
                track = parse_track_info(tds[0].text, track_name, uri_path)
                track["artist"] = tds[2].text.strip()
                tracks.append(track)

        track_lists.append({"section": section, "tracks": tracks, "info": info})
        h2 = h2.find_next_sibling("h2")

    return track_lists


def parse_infobox(infobox):
    """
    Parse the 'infobox' element from a wiki page into a more easily used data format

    :param infobox: Beautiful soup <table class="infobox"> element
    :return dict: The parsed data
    """
    parsed = {}
    for i, tr in enumerate(infobox.find_all("tr")):
        # log.debug("Processing tr: {}".format(tr))
        if i == 0:
            parsed["name"] = tr.text.strip()
        elif i == 1:
            continue    # Image
        elif i == 2:
            parsed["type"], artist = map(str.strip, tr.text.strip().split(" by "))
            for a in tr.find_all("a"):
                if a.text == artist:
                    href = a.get("href") or ""
                    parsed["artist"] = {artist: href[6:] if href.startswith("/wiki/") else href}
                    break
            else:
                parsed["artist"] = {artist: None}
        else:
            th = tr.find("th")
            if not th or th.get("colspan"):
                break
            key = th.text.strip().lower()
            val_ele = tr.find("td")

            if key == "released":
                value = []
                val = val_ele.text.strip()
                try:
                    dt = datetime_with_tz(val, "%d %B %Y")
                except Exception as e:
                    raise WikiEntityParseException("Unexpected release date format: {!r}".format(val)) from e
                else:
                    value.append((dt, None))
            elif key == "length":
                value = [(val_ele.text.strip(), None)]
            elif key in ("agency", "associated", "composer", "current", "label", "writer"):
                anchors = list(val_ele.find_all("a"))
                if anchors:
                    value = {a.text: a.get("href") for a in anchors}
                else:
                    ele_children = list(val_ele.children)
                    if not isinstance(ele_children[0], NavigableString) and ele_children[0].name == "ul":
                        value = {li.text: None for li in ele_children[0].find_all("li")}
                    else:
                        value = {name: None for name in str2list(val_ele.text)}
            else:
                value = val_ele.text.strip()

            parsed[key] = value
    return parsed


def parse_wikipedia_album_page(uri_path, clean_soup, side_info):
    unexpected_num_fmt = "Unexpected disk number format for {}: {!r}"
    bad_intro_fmt = "Unexpected album intro sentence format in {}: {!r}"
    album0 = {}
    intro_text = clean_soup.text.strip()
    intro_match = re.match("^(.*?)\s+is\s+(?:a|the)\s+(.*?)\.\s", intro_text)
    if not intro_match:
        raise WikiEntityParseException(bad_intro_fmt.format(uri_path, intro_text[:200]))

    album0["title_parts"] = parse_intro_name(intro_match.group(1))  # base, cjk, stylized, aka

    details_str = intro_match.group(2)
    details = list(details_str.split())
    album0["repackage"] = False
    try:
        album0["num"], album0["type"] = _album_num_type(details)
    except ValueError:
        raise WikiEntityParseException(bad_intro_fmt.format(uri_path, intro_text[:200])) from e

    # links = []
    # for ele in clean_soup.children:
    #     if isinstance(ele, NavigableString):
    #         continue
    #     elif ele.name in ("h1", "h2", "h3", "h4"):
    #         break
    #     links.extend((a.text, a.get("href")) for a in ele.find_all("a"))
    # album0["links"] = links
    album0["released"] = _first_side_info_val(side_info, "released")
    album0["length"] = _first_side_info_val(side_info, "length")
    album0["name"] = side_info.get("name")
    album0["track_lists"] = []

    albums = [album0]
    disk_rx = re.compile(r"^Dis[ck]\s+(\S+)\s*[{}]?\s*(.*)$".format(DASH_CHARS + ":"), re.IGNORECASE)
    album = album0
    for track_tbl in clean_soup.find_all("table", class_="tracklist"):
        last_ele = track_tbl.previous_sibling
        while isinstance(last_ele, NavigableString):
            last_ele = last_ele.previous_sibling

        if last_ele and last_ele.name == "h3":
            title_parts = parse_intro_name(last_ele.text.strip())
            repkg_title = title_parts[0]
            album = {
                "track_lists": [], "title_parts": title_parts, "repackage": True, "repackage_of_href": uri_path,
                "repackage_of_title": repkg_title
            }
            if len(albums) == 1:
                album0["repackage_href"] = uri_path
                album0["repackage_title"] = repkg_title
            albums.append(album)

        section_th = track_tbl.find(lambda ele: ele.name == "th" and ele.get("colspan"))
        section = section_th.text.strip() if section_th else None
        if section and section.lower().startswith(("disk", "disc")):
            m = disk_rx.match(section)
            if not m:
                raise WikiEntityParseException(unexpected_num_fmt.format(uri_path, section))
            try:
                disk = NUM2INT[m.group(1).lower()]
            except KeyError as e:
                raise WikiEntityParseException(unexpected_num_fmt.format(uri_path, m.group(1))) from e
            section = m.group(2).strip() or None
        else:
            disk = 1

        tracks = []
        for tr in track_tbl.find_all("tr"):
            tds = tr.find_all("td")
            if len(tds) >= 3:
                tracks.append(parse_track_info(tds[0].text, tds[1].text, uri_path, tds[-1].text.strip()))

        album["track_lists"].append({"section": section, "tracks": tracks, "disk": disk})

    for album in albums:
        album["artists"] = side_info.get("artist", {})

    return albums


def edition_combinations(editions, next_track):
    next_track -= 1
    candidates = []
    for i in range(len(editions)):
        for combo in combinations(editions, i):
            tracks = sorted(t["num"] for t in chain.from_iterable(edition["tracks"] for edition in combo))
            if tracks and len(set(tracks)) == len(tracks) == max(tracks) == next_track and min(tracks) == 1:
                candidates.append(combo)

    if not candidates:
        for edition in editions:
            tracks = sorted(t["num"] for t in edition["tracks"])
            if tracks and len(set(tracks)) == len(tracks) == max(tracks) == next_track and min(tracks) == 1:
                candidates.append([edition])

    return list({tuple(e.get("section") or "" for e in combo): combo for combo in candidates}.values())


def multi_lang_name(eng_name, cjk_name):
    if eng_name and cjk_name:
        return "{} ({})".format(eng_name, cjk_name)
    else:
        return eng_name or cjk_name


def comparison_type_check(obj, other, req_type, op):
    if not isinstance(other, req_type):
        fmt = "{!r} is not supported between instances of {!r} and {!r}"
        raise TypeError(fmt.format(op, type(obj).__name__, type(other).__name__))


if __name__ == "__main__":
    from ds_tools.logging import LogManager
    lm = LogManager.create_default_logger(2, log_path=None, entry_fmt="%(asctime)s %(name)s %(message)s")
