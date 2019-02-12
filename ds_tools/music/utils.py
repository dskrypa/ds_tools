#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
:author: Doug Skrypa
"""

import logging
import re
from collections import OrderedDict
from enum import Enum
from urllib.parse import urlparse

# import Levenshtein as lev
from fuzzywuzzy import utils as fuzz_utils

from ..utils import (
    RecursiveDescentParser, UnexpectedTokenError, is_any_cjk, ParentheticalParser, contains_any_cjk, is_hangul
)

__all__ = [
    "SongTitleParser", "DiscographyEntryParser", "sanitize", "unsurround", "_normalize_title", "parse_artist_name",
    "split_name", "eng_cjk_sort", "categorize_langs", "LangCat", "parse_discography_entry"
]
log = logging.getLogger("ds_tools.music.utils")

NUM_STRIP_TBL = str.maketrans({c: "" for c in "0123456789"})
PATH_SANITIZATION_DICT = {c: "" for c in "*;?<>\""}
PATH_SANITIZATION_DICT.update({"/": "_", ":": "-", "\\": "_", "|": "-"})
PATH_SANITIZATION_TABLE = str.maketrans(PATH_SANITIZATION_DICT)
QMARKS = "\"“"


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


def unsurround(a_str):
    for a, b in (("\"", "\""), ("(", ")"), ("“", "“")):
        if a_str.startswith(a) and a_str.endswith(b):
            a_str = a_str[1:-1].strip()
    return a_str


def _normalize_title(title):
    return re.sub("\s+", " ", fuzz_utils.full_process(title, force_ascii=False))


def parse_artist_name(intro_text):
    intro_text = intro_text.strip()
    first_sentence = intro_text[:intro_text.index(". ") + 1].strip()    # Note: space is intentional
    parser = ParentheticalParser()
    try:
        parts = parser.parse(first_sentence)    # Note: returned strs already stripped of leading/trailing spaces
    except Exception as e:
        raise ValueError("Unable to parse artist name from intro: {}".format(first_sentence)) from e

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
    aka_leads = ("aka", "a.k.a.", "also known as")
    for part in map(str.strip, re.split("[;,]", details)):
    # for part in map(str.strip, details.split(";")):
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


def parse_artist_name1(intro_text):
    m = re.match("^(.*?)\s+\((.*?)\)", intro_text)
    if not m:
        raise ValueError("Unexpected intro format: {}".format(intro_text[:200]))
    stylized = None
    eng, cjk = map(str.strip, m.groups())
    # log.debug("Processing name {!r}/{!r}".format(eng, cjk))
    if "(" in cjk and "(" in eng:
        # log.debug("Attempting to extract name with parenthases: {!r}".format(cjk))
        m = re.match("^(.*)\s*\((.*?\(.*?\).*?)\)", intro_text)
        if m:
            eng, cjk = map(str.strip, m.groups())

    if not is_any_cjk(cjk):
        cjk_err_fmt = "Unexpected CJK name format for {!r}/{!r} in: {}"
        stylized_m = re.match("([^;]+);\s*stylized as\s*(.*)", cjk)
        if stylized_m:
            cjk, stylized = map(str.strip, stylized_m.groups())
        else:
            cjk_m = re.match("(?:(?:Korean|Hangul|Japanese|Chinese):\s*)?([^;,]+)[;,]", cjk)
            if cjk_m:
                grp = cjk_m.group(1).strip()
                if is_any_cjk(grp):
                    cjk = grp
                else:
                    m = re.search("(?:Korean|Hangul|Japanese|Chinese):(.*?)[,;]", cjk)
                    if m:
                        cjk = m.group(1).strip()
                        if not is_any_cjk(cjk):
                            raise ValueError(cjk_err_fmt.format(eng, cjk, intro_text[:200]))
            else:
                if eng not in ("yyxy", "iKON", "AOA Cream"):
                    raise ValueError(cjk_err_fmt.format(eng, cjk, intro_text[:200]))
    return eng, cjk, stylized


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


def eng_cjk_sort(strs, langs=None):
    """
    :param str|tuple|list|iterator strs: A single string or a tuple/list with 2 elements
    :param LangCat|tuple|None langs: A single Langs value or a 2-tuple of Langs (ENG/CJK only) or None
    :return tuple: (str(eng), str(cjk))
    """
    if langs is None:
        langs = categorize_langs([strs] if isinstance(strs, str) else strs)
        if isinstance(strs, str):
            langs = langs[0]
    if langs == (LangCat.ENG, LangCat.CJK):
        return strs
    elif langs == (LangCat.CJK, LangCat.ENG):
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


def parse_discography_entry(artist, ele, album_type, lang):
    ele_text = ele.text.strip()
    try:
        parsed = ParentheticalParser().parse(ele_text)
    except Exception as e:
        log.warning("Unhandled discography entry format {!r} for {}".format(ele_text, artist), extra={"red": True})
        return None

    base_type = album_type and (album_type[:-2] if re.search(r"_\d$", album_type) else album_type).lower() or ""
    primary = parsed.pop(0)[:-1].strip() if base_type == "feature" and parsed[0].endswith("-") else artist._uri_path
    year = int(parsed.pop()) if len(parsed[-1]) == 4 and parsed[-1].isdigit() else None
    title = parsed.pop(0)
    collaborators, misc_info = [], []
    for item in parsed:
        if item.lower().startswith(("with", "feat")):
            item = item.split(maxsplit=1)[1]    # remove the with/feat prefix
            collaborators.extend(re.split("(?: and |,|;)", item))
        else:
            misc_info.append(item)

    is_feature_or_collab = base_type in ("features", "collaborations")
    is_ost = base_type in ("ost", "osts")

    first_a = ele.find("a")
    if first_a:
        link_href = first_a.get("href") or ""
        link_text = first_a.text
        if title != link_text and not is_feature_or_collab:
            # if is_feature_or_collab: likely a feature / single with a link to a collaborator
            if not any(title.replace("(", c).replace(")", c) == link_text for c in "-~"):
                log.debug("Unexpected first link text {!r} for album {!r}".format(link_text, title))

        if not link_href.startswith("http"):  # If it starts with http, then it is an external link
            uri_path = link_href[6:] or None
            wiki = "kpop.fandom.com"
        else:
            url = urlparse(link_href)
            if url.hostname == "en.wikipedia.org":
                uri_path = url.path[6:]
                wiki = "en.wikipedia.org"
                # Probably a collaboration song, so title is likely a song and not the album title
            else:
                uri_path = None
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
        "title": title, "primary_artist": primary, "type": album_type, "base_type": base_type, "year": year,
        "collaborators": collaborators, "misc_info": misc_info, "language": lang, "uri_path": uri_path, "wiki": wiki,
        "is_feature_or_collab": is_feature_or_collab, "is_ost": is_ost
    }
    return info


if __name__ == "__main__":
    from ds_tools.logging import LogManager
    lm = LogManager.create_default_logger(2, log_path=None, entry_fmt="%(asctime)s %(name)s %(message)s")
