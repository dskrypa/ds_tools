#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging
import re

__all__ = ["Token", "RecursiveDescentParser", "UnexpectedTokenError"]
log = logging.getLogger("ds_tools.utils.text_processing")


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

    def __init__(self):
        self.pattern = re.compile("|".join("(?P<{}>{})".format(k, v) for k, v in self.TOKENS.items()))

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


class UnexpectedTokenError(SyntaxError):
    """Exception to be raised when encountering an unexpected token"""
