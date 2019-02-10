#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging
import re
import string
from collections import OrderedDict

__all__ = ["Token", "RecursiveDescentParser", "UnexpectedTokenError", "strip_punctuation", "ParentheticalParser"]
log = logging.getLogger("ds_tools.utils.text_processing")

PUNC_STRIP_TBL = str.maketrans({c: "" for c in string.punctuation})
QMARKS = "\"“"


def strip_punctuation(a_str):
    return re.sub("\s+", "", a_str).translate(PUNC_STRIP_TBL)


class Token:
    def __init__(self, tok_type, value):
        self.type = tok_type
        self.value = value
        # log.debug("Found {!r}".format(self))

    def __repr__(self):
        return "<{}({!r}:{!r})>".format(type(self).__name__, self.type, self.value)


class RecursiveDescentParser:
    _entry_point = None
    _strip = False
    TOKENS = {}

    def __init_subclass__(cls, **kwargs):                                                               # Python 3.6+
        cls.pattern = re.compile("|".join("(?P<{}>{})".format(k, v) for k, v in cls.TOKENS.items()))

    def tokenize(self, text):
        # noinspection PyUnresolvedReferences
        scanner = self.pattern.scanner(text.strip() if self._strip else text)
        for m in iter(scanner.match, None):
            self._pos = m.span()[0]             # While this token may start at this pos, it will be stored in next_tok,
            yield Token(m.lastgroup, m.group()) # so the current token being processed at this point ends at this pos

    # noinspection PyAttributeOutsideInit
    def parse(self, text):
        self._pos = 0
        self._full = text
        self.tokens = self.tokenize(text)
        self.tok = None                     # Last symbol consumed
        self.next_tok = None                # Next symbol tokenized
        self._advance()                     # Load first lookahead taken
        try:
            return getattr(self, self._entry_point)()
        except AttributeError as e:
            raise AttributeError("{} requires a valid _entry_point".format(type(self).__name__)) from e

    @property
    def _remaining(self):
        return self._full[self._pos:]

    def _advance(self):
        self.tok, self.next_tok = self.next_tok, next(self.tokens, None)

    def _peek(self, token_type):
        return self.next_tok and self.next_tok.type == token_type

    def _accept(self, token_type):
        if self.next_tok and self.next_tok.type == token_type:
            self._advance()
            return True
        return False

    def _expect(self, token_type):
        if not self._accept(token_type):
            raise UnexpectedTokenError("Expected {}".format(token_type))


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
                # log.debug("Parsed {!r} (nested={}); next token={!r}".format(parenthetical, nested, self.next_tok))
                # if not parts and not nested and not self._peek("WS"):
                if not nested and not self._peek("WS") and self.next_tok is not None:
                    text += self._nested_fmts[tok_type].format(parenthetical)
                else:
                    parts.append((parenthetical, nested, tok_type))
            elif any(self._accept(tok_type) for tok_type in self._content_tokens):
                text += self.tok.value
            else:
                raise UnexpectedTokenError("Unexpected {!r} token {!r} in {!r}".format(
                    self.next_tok.type, self.next_tok.value, self._full
                ))

        if text.strip():
            parts.append(text.strip())

        single_idxs = set()
        had_nested = False
        for i, part in enumerate(parts):
            if isinstance(part, tuple):
                nested = part[1]
                had_nested = had_nested or nested
                if not nested:
                    single_idxs.add(i)

        # log.debug("{!r} => {} [nested: {}][singles: {}]".format(self._full, parts, had_nested, sorted(single_idxs)))
        if had_nested and single_idxs:
            single_idxs = sorted(single_idxs)
            while single_idxs:
                i = single_idxs.pop(0)
                for ti in (i - 1, i + 1):
                    if (ti < 0) or (ti > (len(parts) - 1)):
                        continue
                    if isinstance(parts[ti], str) and parts[ti].strip():
                        parenthetical, nested, tok_type = parts[i]
                        formatted = self._nested_fmts[tok_type].format(parenthetical)
                        parts[ti] = (formatted + parts[ti]) if ti > i else (parts[ti] + formatted)
                        parts.pop(i)
                        single_idxs = [idx - 1 for idx in single_idxs]
                        break

        cleaned = (part for part in map(str.strip, (p[0] if isinstance(p, tuple) else p for p in parts)) if part)
        return [part for part in cleaned if part not in "\"“()（）[]"]


class UnexpectedTokenError(SyntaxError):
    """Exception to be raised when encountering an unexpected token"""
