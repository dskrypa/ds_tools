"""
Some old attempts at recursive descent parsers.

:author: Doug Skrypa
"""

import logging
import re

from .text_processing import chars_by_category

__all__ = [
    'Token',
    'RecursiveDescentParser',
    'UnexpectedTokenError',
    'ParentheticalParser',
    'ListBasedRecursiveDescentParser',
    'ParentheticalListParser',
]
log = logging.getLogger(__name__)


class Token:
    __slots__ = ('type', 'value')

    def __init__(self, tok_type, value):
        self.type = tok_type
        self.value = value
        # log.debug('Found {!r}'.format(self))

    def __repr__(self) -> str:
        return f'<{self.__class__.__name__}({self.type!r}:{self.value!r})>'


class RecursiveDescentParser:
    _entry_point = None
    _strip = False
    _ignore_case = False
    TOKENS = {}

    def __init_subclass__(cls, **kwargs):                                                               # Python 3.6+
        if cls._ignore_case:
            cls.pattern = re.compile('|'.join('(?P<{}>{})'.format(k, v) for k, v in cls.TOKENS.items()), re.IGNORECASE)
        else:
            cls.pattern = re.compile('|'.join('(?P<{}>{})'.format(k, v) for k, v in cls.TOKENS.items()))

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
            raise AttributeError('{} requires a valid _entry_point'.format(type(self).__name__)) from e

    @property
    def _remaining(self):
        return self._full[self._pos:]

    def _find_next(self, token_type):
        cls = type(self)
        parser = cls()
        parser._pos = 0
        tokens = parser.tokenize(self._full)
        # noinspection PyTypeChecker
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

    def _last(self, token_type):
        return self.prev_tok and self.prev_tok.type == token_type

    def _last_any(self, token_types):
        return self.prev_tok and self.prev_tok.type in token_types

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
            raise UnexpectedTokenError('Expected {}'.format(token_type))


class ListBasedRecursiveDescentParser(RecursiveDescentParser):
    _opener2closer = {}

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
    def _lookahead_any(self, token_types, with_tok=False):
        last = len(self.tokens) - 1
        i = self._idx
        while i <= last:
            pos, token = self.tokens[i]
            if token.type in token_types:
                return (pos, token) if with_tok else pos
            i += 1
        return (-1, None) if with_tok else -1

    def _peek_seq(self, token_types):
        """
        :param Iterable token_types: Iterable object that yields token type strings
        :return: True if all of the provided tokens occur from the current point in parsing forward in the order they
          were given, False otherwise
        """
        expected = iter(token_types)
        matched_one = False
        for pos, token in self.tokens[self._idx:]:
            try:
                if next(expected) != token.type:
                    return False
            except StopIteration:
                return matched_one
            else:
                matched_one = True

        try:
            next(expected)
        except StopIteration:
            return matched_one
        else:
            return False

    def _lookahead_unpaired(self, closer):
        """Find the position of the next closer that does not have a preceding opener in the remaining tokens"""
        openers = {opener for opener, _closer in self._opener2closer.items() if _closer == closer}
        opened = 0
        closed = 0
        # log.debug('Looking for next {!r} from idx={} in {}'.format(closer, self._idx, self.tokens))
        for pos, token in self.tokens[self._idx:]:
            if token.type == closer:
                closed += 1
                if closed > opened:
                    return pos
            elif token.type in openers:
                opened += 1
        return -1


def _all_whitespace():
    try:
        chars = _all_whitespace._chars
    except AttributeError:
        import sys
        chars = _all_whitespace._chars = ''.join(re.findall(r'\s', ''.join(chr(c) for c in range(sys.maxunicode + 1))))
    return chars


class ParentheticalListParser(RecursiveDescentParser):
    _entry_point = 'content'
    _strip = True
    _opener2closer = {'LPAREN': 'RPAREN', 'LBPAREN': 'RBPAREN', 'LBRKT': 'RBRKT'}
    _nested_fmts = {'LPAREN': '({})', 'LBPAREN': '({})', 'LBRKT': '[{}]'}
    _content_tokens = ['TEXT', 'WS'] + [v for k, v in _opener2closer.items() if k != v]
    _req_preceders = ['WS'] + list(_opener2closer.values())
    TOKENS = {
        'LPAREN': r'\(',
        'RPAREN': r'\)',
        'LBPAREN': '（',
        'RBPAREN': '）',
        'LBRKT': r'\[',
        'RBRKT': r'\]',
        'DELIM': '[,;]',
        'WS': r'\s+',
        'TEXT': fr'[^,;()（）\[\]{_all_whitespace()}]+',
    }

    def __init__(self, require_preceder=True):
        self._require_preceder = require_preceder

    def parenthetical(self, closer='RPAREN'):
        """
        parenthetical ::= ( { text | WS | ( parenthetical ) }* )
        """
        text = ''
        nested = False
        while self.next_tok:
            if self._accept(closer):
                return text, nested
            elif self._accept_any(self._opener2closer):
                tok_type = self.tok.type
                text += self._nested_fmts[tok_type].format(self.parenthetical(self._opener2closer[tok_type])[0])
                nested = True
            else:
                self._advance()
                text += self.tok.value
        return text, nested

    def _should_not_enter(self):
        return self._require_preceder and self.prev_tok.type not in self._req_preceders and self._peek('TEXT')

    def content(self):
        """
        item ::= text { (parenthetical) }*
        content :: = item {delim item}*
        """
        text = ''
        item = []
        parts = []
        while self.next_tok:
            if self._accept_any(self._opener2closer):
                tok_type = self.tok.type
                if text and self._should_not_enter():
                    text += self.tok.value
                    continue

                text = text.strip()
                if text:
                    item.append(text)
                    text = ''
                parenthetical, nested = self.parenthetical(self._opener2closer[tok_type])
                item.append(parenthetical)
            elif self._accept('DELIM'):
                text = text.strip()
                if text:
                    item.append(text)
                    text = ''
                if item:
                    parts.append(item)
                    item = []
            elif self._accept_any(self._content_tokens):
                text += self.tok.value
            else:
                raise UnexpectedTokenError('Unexpected {!r} token {!r} in {!r}'.format(
                    self.next_tok.type, self.next_tok.value, self._full
                ))

        text = text.strip()
        if text:
            item.append(text)
        if item:
            parts.append(item)

        return parts


class ParentheticalParser(RecursiveDescentParser):
    _entry_point = 'content'
    _strip = True
    _opener2closer = {'LPAREN': 'RPAREN', 'LBPAREN': 'RBPAREN', 'LBRKT': 'RBRKT', 'QUOTE': 'QUOTE', 'DASH': 'DASH'}
    _nested_fmts = {'LPAREN': '({})', 'LBPAREN': '({})', 'LBRKT': '[{}]', 'QUOTE': '{!r}', 'DASH': '({})'}
    _content_tokens = ['TEXT', 'WS'] + [v for k, v in _opener2closer.items() if k != v]
    _req_preceders = ['WS'] + list(_opener2closer.values())
    _qmarks = '\"“'
    TOKENS = {
        'QUOTE': f'[{_qmarks}]',
        'LPAREN': r'\(',
        'RPAREN': r'\)',
        'LBPAREN': '（',
        'RBPAREN': '）',
        'LBRKT': r'\[',
        'RBRKT': r'\]',
        'WS': r'\s+',
        'DASH': '[{}]'.format(chars_by_category('Pd') + '~'),
        'TEXT': r'[^{}{}()（）\[\]{}]+'.format(chars_by_category('Pd') + '~', _qmarks, _all_whitespace()),
    }

    def __init__(self, selective_recombine=True, require_preceder=True):
        self._selective_recombine = selective_recombine
        self._require_preceder = require_preceder

    def parenthetical(self, closer='RPAREN'):
        """
        parenthetical ::= ( { text | WS | ( parenthetical ) }* )
        """
        # log.debug('Opening {}'.format(closer))
        text = ''
        nested = False
        while self.next_tok:
            if self._accept(closer):
                # log.debug('[closing] Closing {}: {} [nested: {}]'.format(closer, text, nested))
                return text, nested
            elif self._accept_any(self._opener2closer):
                tok_type = self.tok.type
                if tok_type == 'DASH':
                    if self.tok.value not in self._remaining:
                        text += self.tok.value
                        continue
                    elif text and self.prev_tok.type != 'WS' and self._peek('TEXT'):
                        text += self.tok.value
                        continue
                text += self._nested_fmts[tok_type].format(self.parenthetical(self._opener2closer[tok_type])[0])
                nested = True
            else:
                self._advance()
                text += self.tok.value
        # log.debug('[closing] Closing {}: {} [nested: {}]'.format(closer, text, nested))
        return text, nested

    def _should_not_enter(self):
        return self._require_preceder and self.prev_tok.type not in self._req_preceders and self._peek('TEXT')

    def content(self):
        """
        content :: = text { (parenthetical) }* { text }*
        """
        text = ''
        parts = []
        while self.next_tok:
            if self._accept_any(self._opener2closer):
                tok_type = self.tok.type
                if text and self._should_not_enter():
                    text += self.tok.value
                    continue
                elif tok_type == 'QUOTE':
                    if any((c not in self._remaining) and (self._full.count(c) % 2 == 1) for c in self._qmarks):
                        log.debug('Unpaired quote found in {!r}'.format(self._full))
                        continue
                elif tok_type == 'DASH':
                    # log.debug('Found DASH ({!r}={}); remaining: {!r}'.format(self.tok.value, ord(self.tok.value), self._remaining))
                    if self._peek('WS') or self.tok.value not in self._remaining:
                        # log.debug('Appending DASH because WS did not follow it or the value does not occur again')
                        text += self.tok.value
                        continue
                    # elif text and self.prev_tok.type != 'WS' and self._peek('TEXT'):
                    #     # log.debug('Appending DASH because text, previous token was {}={!r}, and the next token is TEXT'.format(self.prev_tok.type, self.prev_tok.value))
                    #     text += self.tok.value
                    #     continue

                if text:
                    parts.append(text)
                    text = ''
                parenthetical, nested = self.parenthetical(self._opener2closer[tok_type])
                # log.debug('Parsed {!r} (nested={}); next token={!r}'.format(parenthetical, nested, self.next_tok))
                # if not parts and not nested and not self._peek('WS'):
                if not nested and not self._peek('WS') and self.next_tok is not None:
                    text += self._nested_fmts[tok_type].format(parenthetical)
                else:
                    parts.append((parenthetical, nested, tok_type))
            elif self._accept_any(self._content_tokens):
                text += self.tok.value
            else:
                raise UnexpectedTokenError('Unexpected {!r} token {!r} in {!r}'.format(
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

            # log.debug('{!r} => {} [nested: {}][singles: {}]'.format(self._full, parts, had_nested, sorted(single_idxs)))
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
        return [part for part in cleaned if part not in '\"“()（）[]']


class UnexpectedTokenError(SyntaxError):
    """Exception to be raised when encountering an unexpected token"""


# noinspection PyUnresolvedReferences
del _all_whitespace._chars
