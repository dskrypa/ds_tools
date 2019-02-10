#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
:author: Doug Skrypa
"""

import logging
import re
from collections import OrderedDict
from enum import Enum

# import Levenshtein as lev
from fuzzywuzzy import utils as fuzz_utils

from ..utils import RecursiveDescentParser, UnexpectedTokenError, is_any_cjk, ParentheticalParser, contains_any_cjk

__all__ = [
    "TitleParser", "AlbumParser", "sanitize", "unsurround", "_normalize_title", "parse_artist_name", "split_name",
    "eng_cjk_sort"
]
log = logging.getLogger("ds_tools.music.utils")

NUM_STRIP_TBL = str.maketrans({c: "" for c in "0123456789"})
PATH_SANITIZATION_DICT = {c: "" for c in "*;?<>\""}
PATH_SANITIZATION_DICT.update({"/": "_", ":": "-", "\\": "_", "|": "-"})
PATH_SANITIZATION_TABLE = str.maketrans(PATH_SANITIZATION_DICT)
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
    m = re.match("^(.*?)\s+\((.*?)\)", intro_text)
    if not m:
        raise ValueError("Unexpected intro format: {}".format(intro_text))
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
    langs = _langs(parts)
    s = "s" if len(parts) > 1 else ""
    log.debug("ParentheticalParser().parse({!r}) => {} part{}: {} ({})".format(name, len(parts), s, parts, langs))
    if len(parts) == 1:
        try:
            eng, cjk = eng_cjk_sort(parts[0], langs[0])
        except ValueError as e:
            raise ValueError("Unable to split {!r} into separate English/CJK strings".format(name)) from e
    elif len(parts) == 2:
        if Langs.MIX not in langs and len(set(langs)) == 2:
            eng, cjk = eng_cjk_sort(parts, langs)           # Name (other lang)
        elif langs[0] == Langs.MIX and langs[1] != Langs.MIX and has_parens(parts[0]):
            eng, cjk = split_name(parts[0])                 # Soloist (other lang) (Group single lang)
            not_used = parts[1]
        elif langs[0] != Langs.MIX and langs[1] == Langs.MIX and has_parens(parts[1]):
            eng, cjk = eng_cjk_sort(parts[0], langs[0])     # Soloist single lang (Group (group other lang))
            try:
                not_used = split_name(parts[1])
            except Exception:
                not_used = parts[1]
        elif langs == (Langs.MIX, Langs.MIX) and all(has_parens(p) for p in parts):
            eng, cjk = split_name(parts[0])                 # Soloist (other lang) [Group (group other lang)]
            try:
                not_used = split_name(parts[1])
            except Exception:
                not_used = parts[1]
    elif len(parts) == 3:
        if Langs.MIX not in langs and len(set(langs)) == 2:
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
    :param str|tuple|list strs: A single string or a tuple/list with 2 elements
    :param Langs|tuple|None langs: A single Langs value or a 2-tuple of Langs (ENG/CJK only) or None
    :return tuple: (str(eng), str(cjk))
    """
    if langs is None:
        langs = _langs([strs] if isinstance(strs, str) else strs)
        if isinstance(strs, str):
            langs = langs[0]
    if langs == (Langs.ENG, Langs.CJK):
        return strs
    elif langs == (Langs.CJK, Langs.ENG):
        return strs[::-1]
    elif isinstance(strs, str):
        if langs == Langs.ENG:
            return strs, ""
        elif langs == Langs.CJK:
            return "", strs
    raise ValueError("Unexpected values: strs={!r}, langs={!r}".format(strs, langs))


def has_parens(text):
    return any(c in text for c in "()[]")


class Langs(Enum):
    ENG = 1
    CJK = 2
    MIX = 3


def _langs(strs):
    return tuple(Langs.CJK if is_any_cjk(s) else Langs.MIX if contains_any_cjk(s) else Langs.ENG for s in strs)


if __name__ == "__main__":
    from ds_tools.logging import LogManager
    lm = LogManager.create_default_logger(2, log_path=None, entry_fmt="%(asctime)s %(name)s %(message)s")
