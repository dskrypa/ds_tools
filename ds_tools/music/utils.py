#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
:author: Doug Skrypa
"""

import logging
import re
from collections import OrderedDict

# import Levenshtein as lev
from fuzzywuzzy import utils as fuzz_utils

from ..utils import contains_hangul, RecursiveDescentParser, UnexpectedTokenError

__all__ = ["TitleParser", "AlbumParser", "sanitize", "eng_name", "han_name", "unsurround", "_normalize_title"]
log = logging.getLogger("ds_tools.music.utils")

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
