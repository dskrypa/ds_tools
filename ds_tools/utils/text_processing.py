"""
Text processing utilities.

:author: Doug Skrypa
"""

import logging
import re
import string
import sys
from collections import OrderedDict, defaultdict
from itertools import chain
from unicodedata import category as unicode_cat

__all__ = [
    "Token", "RecursiveDescentParser", "UnexpectedTokenError", "strip_punctuation", "ParentheticalParser", "DASH_CHARS",
    "QMARKS", "ALL_WHITESPACE", "CHARS_BY_CATEGORY", "ListBasedRecursiveDescentParser"
]
log = logging.getLogger(__name__)


def _chars_by_category():
    chars_by_cat = defaultdict(list)
    for c in map(chr, range(sys.maxunicode + 1)):
        chars_by_cat[unicode_cat(c)].append(c)
    return {cat: "".join(chars) for cat, chars in chars_by_cat.items()}


ALL_WHITESPACE = "".join(re.findall(r"\s", "".join(chr(c) for c in range(sys.maxunicode + 1))))
CHARS_BY_CATEGORY = _chars_by_category()    # Note: ALL_WHITESPACE is a superset of CHARS_BY_CATEGORY["Zs"]
DASH_CHARS = CHARS_BY_CATEGORY["Pd"] + "~"
# ALL_PUNCTUATION = "".join(chain.from_iterable(chars for cat, chars in CHARS_BY_CATEGORY.items() if cat.startswith("P")))
PUNC_STRIP_TBL = str.maketrans({c: "" for c in string.punctuation})
QMARKS = "\"“"


def strip_punctuation(a_str):
    return re.sub(r"\s+", "", a_str).translate(PUNC_STRIP_TBL)


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
        self.prev_tok = None                # Previous symbol consumed
        self.tok = None                     # Current / most recently consumed symbol
        self.next_tok = None                # Next symbol tokenized
        self._advance()                     # Load first lookahead taken
        try:
            return getattr(self, self._entry_point)()
        except AttributeError as e:
            raise AttributeError("{} requires a valid _entry_point".format(type(self).__name__)) from e

    @property
    def _remaining(self):
        return self._full[self._pos:]

    def _find_next(self, token_type):
        cls = type(self)
        parser = cls()
        parser._pos = 0
        tokens = parser.tokenize(self._full)
        for token in iter(tokens, None):
            if parser._pos < self._pos:
                continue
            elif token.type == token_type:
                return parser._pos
        return -1

    def _advance(self):
        self.prev_tok, self.tok, self.next_tok = self.tok, self.next_tok, next(self.tokens, None)

    def _peek(self, token_type):
        return self.next_tok and self.next_tok.type == token_type

    def _peek_any(self, token_types):
        return self.next_tok and self.next_tok.type in token_types

    def _accept(self, token_type):
        if self.next_tok and self.next_tok.type == token_type:
            self._advance()
            return True
        return False

    def _accept_any(self, token_types):
        if self.next_tok and self.next_tok.type in token_types:
            self._advance()
            return True
        return False

    def _expect(self, token_type):
        if not self._accept(token_type):
            raise UnexpectedTokenError("Expected {}".format(token_type))


class ListBasedRecursiveDescentParser(RecursiveDescentParser):
    def tokenize(self, text):
        # noinspection PyUnresolvedReferences
        scanner = self.pattern.scanner(text.strip() if self._strip else text)
        return [(m.span()[0], Token(m.lastgroup, m.group())) for m in iter(scanner.match, None)]

    # noinspection PyAttributeOutsideInit
    def parse(self, text):
        self._idx = -1
        return super().parse(text)

    def __next_token(self):
        self._idx += 1
        try:
            # noinspection PyUnresolvedReferences
            self._pos, token = self.tokens[self._idx]
        except IndexError:
            return None
        else:
            return token

    def _advance(self):
        self.prev_tok, self.tok, self.next_tok = self.tok, self.next_tok, self.__next_token()

    # noinspection PyTypeChecker, PyUnresolvedReferences
    def _lookahead(self, token_type):
        last = len(self.tokens) - 1
        i = self._idx
        while i <= last:
            pos, token = self.tokens[i]
            if token.type == token_type:
                return pos
            i += 1
        return -1

    # noinspection PyTypeChecker, PyUnresolvedReferences
    def _lookahead_any(self, token_types):
        last = len(self.tokens) - 1
        i = self._idx
        while i <= last:
            pos, token = self.tokens[i]
            if token.type in token_types:
                return pos
            i += 1
        return -1


class ParentheticalParser(RecursiveDescentParser):
    _entry_point = "content"
    _strip = True
    _opener2closer = {"LPAREN": "RPAREN", "LBPAREN": "RBPAREN", "LBRKT": "RBRKT", "QUOTE": "QUOTE", "DASH": "DASH"}
    _nested_fmts = {"LPAREN": "({})", "LBPAREN": "({})", "LBRKT": "[{}]", "QUOTE": "{!r}", "DASH": "({})"}
    _content_tokens = ["TEXT", "WS"] + [v for k, v in _opener2closer.items() if k != v]
    _req_preceders = ["WS"] + list(_opener2closer.values())
    TOKENS = OrderedDict([
        ("QUOTE", "[{}]".format(QMARKS)),
        ("LPAREN", "\("),
        ("RPAREN", "\)"),
        ("LBPAREN", "（"),
        ("RBPAREN", "）"),
        ("LBRKT", "\["),
        ("RBRKT", "\]"),
        ("WS", "\s+"),
        ("DASH", "[{}]".format(DASH_CHARS)),
        ("TEXT", "[^{}{}()（）\[\]{}]+".format(DASH_CHARS, QMARKS, ALL_WHITESPACE)),
    ])

    def __init__(self, selective_recombine=True):
        self._selective_recombine = selective_recombine

    def parenthetical(self, closer="RPAREN"):
        """
        parenthetical ::= ( { text | WS | ( parenthetical ) }* )
        """
        # log.debug('Opening {}'.format(closer))
        text = ""
        nested = False
        while self.next_tok:
            if self._accept(closer):
                # log.debug('[closing] Closing {}: {} [nested: {}]'.format(closer, text, nested))
                return text, nested
            elif self._accept_any(self._opener2closer):
                tok_type = self.tok.type
                if tok_type == "DASH":
                    if self.tok.value not in self._remaining:
                        text += self.tok.value
                        continue
                    elif text and self.prev_tok.type != "WS" and self._peek("TEXT"):
                        text += self.tok.value
                        continue
                text += self._nested_fmts[tok_type].format(self.parenthetical(self._opener2closer[tok_type])[0])
                nested = True
            else:
                self._advance()
                text += self.tok.value
        # log.debug('[closing] Closing {}: {} [nested: {}]'.format(closer, text, nested))
        return text, nested

    def content(self):
        """
        content :: = text { (parenthetical) }* { text }*
        """
        text = ""
        parts = []
        while self.next_tok:
            if self._accept_any(self._opener2closer):
                tok_type = self.tok.type
                if text and self.prev_tok.type not in self._req_preceders and self._peek("TEXT"):
                    text += self.tok.value
                    continue
                elif tok_type == "QUOTE":
                    if any((c not in self._remaining) and (self._full.count(c) % 2 == 1) for c in QMARKS):
                        log.debug("Unpaired quote found in {!r}".format(self._full))
                        continue
                elif tok_type == "DASH":
                    # log.debug("Found DASH ({!r}={}); remaining: {!r}".format(self.tok.value, ord(self.tok.value), self._remaining))
                    if self._peek("WS") or self.tok.value not in self._remaining:
                        # log.debug("Appending DASH because WS did not follow it or the value does not occur again")
                        text += self.tok.value
                        continue
                    # elif text and self.prev_tok.type != "WS" and self._peek("TEXT"):
                    #     # log.debug("Appending DASH because text, previous token was {}={!r}, and the next token is TEXT".format(self.prev_tok.type, self.prev_tok.value))
                    #     text += self.tok.value
                    #     continue

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
            elif self._accept_any(self._content_tokens):
                text += self.tok.value
            else:
                raise UnexpectedTokenError("Unexpected {!r} token {!r} in {!r}".format(
                    self.next_tok.type, self.next_tok.value, self._full
                ))

        if text.strip():
            parts.append(text.strip())

        if self._selective_recombine:
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
