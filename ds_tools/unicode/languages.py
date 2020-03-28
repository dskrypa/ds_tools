"""
Tools for identifying the languages used in text.

:author: Doug Skrypa
"""

import logging
import re
import string
import unicodedata
from enum import Enum
from typing import Union, Set, Optional, Tuple, Generator, List, Iterable, Container

from cachetools import LRUCache
try:
    from pykakasi import kakasi
except ImportError:
    kakasi = None

from ..caching import cached
from ..core import classproperty
from ..utils import ALL_PUNCTUATION, ALL_SYMBOLS
from .hangul import hangul_romanized_permutations, matches_hangul_permutation
from .ranges import *

__all__ = [
    'is_hangul', 'contains_hangul', 'is_japanese', 'contains_japanese', 'is_cjk', 'contains_cjk',
    'is_any_cjk', 'contains_any_cjk', 'LangCat', 'romanized_permutations', 'matches_permutation'
]
log = logging.getLogger(__name__)

ALL_PUNC_SYMBOLS_WS = ALL_PUNCTUATION + ALL_SYMBOLS + string.whitespace
LANG_CAT_NAMES = ['NULL', 'MIX', 'English', 'Korean', 'Japanese', 'Chinese', 'Thai', 'Greek', 'Cyrillic', 'UNKNOWN']
NUM_STRIP_TBL = str.maketrans({c: '' for c in '0123456789'})
PUNC_STRIP_TBL = str.maketrans({c: '' for c in string.punctuation})
PUNC_SYMBOL_STRIP_TBL = str.maketrans({c: '' for c in ALL_PUNCTUATION + ALL_SYMBOLS})


class LangCat(Enum):
    UNK = -1
    NUL = 0
    MIX = 1
    ENG = 2
    HAN = 3
    JPN = 4
    CJK = 5
    THAI = 6
    GRK = 7
    CYR = 8

    def __lt__(self, other):
        return self.value < other.value

    @classproperty
    def non_eng_cats(self) -> Tuple['LangCat', ...]:
        return LangCat.UNK, LangCat.HAN, LangCat.JPN, LangCat.CJK, LangCat.THAI, LangCat.GRK, LangCat.CYR

    @classproperty
    def asian_cats(self) -> Tuple['LangCat', ...]:
        return LangCat.HAN, LangCat.JPN, LangCat.CJK, LangCat.THAI

    asian = asian_cats

    @classmethod
    def _ranges(cls) -> Generator[Tuple['LangCat', List[Tuple[int, int]]], None, None]:
        yield cls.ENG, LATIN_RANGES
        yield cls.HAN, HANGUL_RANGES
        yield cls.JPN, JAPANESE_RANGES
        yield cls.THAI, THAI_RANGES
        yield cls.CJK, CJK_RANGES
        yield cls.GRK, GREEK_COPTIC_RANGES
        yield cls.CYR, CYRILLIC_RANGES

    @classmethod
    @cached(LRUCache(200), exc=True)
    def categorize(cls, text: Optional[str], detailed=False) -> Union['LangCat', Set['LangCat']]:
        if detailed:
            return set(cls.categorize(c) for c in text)
        elif not text:
            return cls.NUL
        elif len(text) == 1:
            dec = ord(text)
            for cat, ranges in cls._ranges():
                if any(a <= dec <= b for a, b in ranges):
                    return cat
            return cls.UNK
        else:
            text = _strip_non_word_chars(text)
            if len(text) == 0:
                return cls.NUL
            else:
                cat = cls.categorize(text[0])
                for c in text[1:]:
                    if cls.categorize(c) != cat:
                        return cls.MIX
                return cat

    @classmethod
    def categorize_all(cls, texts: Iterable[Optional[str]], detailed=False) -> Tuple['LangCat', ...]:
        return tuple(cls.categorize(t, detailed) for t in texts)

    @classmethod
    @cached(LRUCache(200), exc=True)
    def matches(cls, text: Optional[str], *cats: 'LangCat', detailed=False) -> bool:
        if detailed:
            text_cats = cls.categorize(text, True)
            return len(text_cats.intersection(cats)) == len(text_cats) == len(cats)
        elif len(cats) > 1:
            return False
        else:
            return cls.categorize(text) == cats[0]

    @classmethod
    def contains_any(cls, text: str, cat: Union['LangCat', Container['LangCat']]) -> bool:
        """
        :param str text: Text to examine
        :param LangCat|list|tuple|set cat: One or more :class:`LangCat` language categories
        :return bool: True if the given text contains a character with the given language category, False otherwise
        """
        cats = [cat] if isinstance(cat, cls) else cat
        if cls.MIX in cats:
            return cls.categorize(text) == cls.MIX
        elif len(text) > 1:
            text = _strip_non_word_chars(text)

        if len(text) == 0:
            return cls.NUL in cats
        for c in text:
            if cls.categorize(c) in cats:
                return True
        return False

    @classmethod
    def contains_any_not(cls, text: str, cat: 'LangCat') -> bool:
        if cat == cls.MIX:
            raise ValueError('{!r} is not supported for {}.contains_any_not()'.format(cat, cls.__name__))
        elif len(text) > 1:
            text = _strip_non_word_chars(text)
        if len(text) == 0:
            return cat != cls.NUL
        for c in text:
            if cls.categorize(c) != cat:
                return True
        return False

    @classmethod
    def for_name(cls, language: str) -> 'LangCat':
        lang = language.lower().strip()
        if lang in ('english', 'eng', 'en', 'spanish'):     # A better enum value would have been latin, since this is
            return cls.ENG                                  # more about unicode than actual language
        elif lang in ('korean', 'hangul', 'kor', 'kr', 'ko'):
            return cls.HAN
        elif lang in ('japanese', 'jp', 'jpn', 'jap'):
            return cls.JPN
        elif lang == 'thai':
            return cls.THAI
        elif lang in ('chinese', 'mandarin', 'chn'):
            return cls.CJK
        elif lang in ('russian',):
            return cls.CYR
        elif lang in ('greek',):
            return cls.GRK
        return cls.UNK

    @classmethod
    def split(cls, text: str, strip=True) -> List[str]:
        if strip:
            text = text.strip()
        if not text:
            return []

        indexes = []
        last = None
        last_char = None
        i = 0
        for c in text:
            if c in ALL_PUNC_SYMBOLS_WS:
                pass
            elif last is None:
                last = cls.categorize(c)
            else:
                current = cls.categorize(c)
                if current != last:
                    last = current
                    if last_char and last_char == '(':
                        indexes.append(i - 1)
                    else:
                        indexes.append(i)
                    i = 0
            i += 1
            last_char = c

        # log.debug('indexes: {}'.format(indexes))
        parts = []
        for idx in indexes:
            part, rem = text[:idx], text[idx:]
            # log.debug('idx={}, part={!r}, rem={!r}'.format(idx, part, rem))
            parts.append(part)
            text = rem

        if text:
            parts.append(text)

        if strip:
            parts = list(map(str.strip, parts))
            for i, part in enumerate(parts):
                if part.endswith(';'):
                    parts[i] = part[:-1].strip()

        for i, part in enumerate(parts):
            if i and part.endswith(')') and not part.startswith('(') and parts[i-1].endswith('('):
                parts[i-1] = parts[i-1][:-1]
                parts[i] = '(' + part

        return parts

    @classmethod
    def sort(cls, texts: Iterable[Optional[str]]):
        return [text for cat, text in sorted((cls.categorize(text), text) for text in texts)]

    @property
    def full_name(self) -> str:
        return LANG_CAT_NAMES[self.value]


def _strip_non_word_chars(text: str) -> str:
    # original = text
    text = re.sub(r'[\d\s]+', '', text).translate(PUNC_SYMBOL_STRIP_TBL)
    # log.debug('_strip_non_word_chars({!r}) => {!r}'.format(original, text))
    return text


def is_hangul(a_str: str) -> bool:
    """
    :param str a_str: A string
    :return bool: True if the given string contains only hangul characters, False otherwise.  Punctuation and spaces are
      ignored
    """
    if len(a_str) < 1:
        return False
    elif len(a_str) > 1:
        a_str = re.sub('\s+', '', a_str).translate(PUNC_STRIP_TBL)
        if len(a_str) < 1:
            return False
        return all(is_hangul(c) for c in a_str)

    as_dec = ord(a_str)
    return any(a <= as_dec <= b for a, b in HANGUL_RANGES)


def is_japanese(a_str: str) -> bool:
    if len(a_str) < 1:
        return False
    elif len(a_str) > 1:
        a_str = re.sub('\s+', '', a_str).translate(PUNC_STRIP_TBL)
        if len(a_str) < 1:
            return False
        return all(is_japanese(c) for c in a_str)

    as_dec = ord(a_str)
    return any(a <= as_dec <= b for a, b in JAPANESE_RANGES)


def is_cjk(a_str: str) -> bool:
    if len(a_str) < 1:
        return False
    elif len(a_str) > 1:
        a_str = re.sub('\s+', '', a_str).translate(PUNC_STRIP_TBL)
        if len(a_str) < 1:
            return False
        return all(is_cjk(c) for c in a_str)

    as_dec = ord(a_str)
    return any(a <= as_dec <= b for a, b in CJK_RANGES)


def is_any_cjk(a_str: str, strip_punc=True, strip_nums=True) -> bool:
    """
    :param str a_str: A string
    :param bool strip_punc: True (default) to strip punctuation before processing when len > 1
    :param bool strip_nums: True (default) to strip numbers before processing when len > 1
    :return bool: True if the given string contains only CJK/Katakana/Hiragana/Hangul characters (ignoring spaces,
      and optionally ignoring punctuation and numbers)
    """
    if len(a_str) < 1:
        return False
    elif len(a_str) > 1:
        a_str = re.sub('\s+', '', a_str)
        if strip_punc:
            a_str = a_str.translate(PUNC_STRIP_TBL)
        if strip_nums:
            a_str = a_str.translate(NUM_STRIP_TBL)
        if len(a_str) < 1:
            return False
        return all(is_any_cjk(c) for c in a_str)

    as_dec = ord(a_str)
    return any(a <= as_dec <= b for a, b in NON_ENG_RANGES)


def contains_hangul(a_str: Optional[str]) -> bool:
    try:
        return any(is_hangul(c) for c in a_str)
    except TypeError:   # likely NoneType is not iterable
        return False


def contains_japanese(a_str: Union[str, Iterable[str]]) -> bool:
    return any(is_japanese(c) for c in a_str)


def contains_cjk(a_str: Union[str, Iterable[str]]) -> bool:
    return any(is_cjk(c) for c in a_str)


def contains_any_cjk(a_str: Union[str, Iterable[str]]) -> bool:
    return any(is_any_cjk(c) for c in a_str)


def _print_unicode_names(a_str: str):
    for c in a_str:
        log.info('{!r}: {}'.format(c, unicodedata.name(c)))


class J2R:
    __instances = {}

    def __new__(cls, mode, include_space=False):
        key = (mode, include_space)
        if key not in cls.__instances:
            obj = super().__new__(cls)
            cls.__instances[key] = obj
        return cls.__instances[key]

    def __init__(self, mode, include_space=False):
        if not getattr(self, '_J2R__initialized', False):
            try:
                k = kakasi()
            except TypeError as e:
                raise RuntimeError('Missing required package: pykakasi') from e
            k._mode.update({'J': 'a', 'H': 'a', 'K': 'a'})
            k.setMode('r', mode)
            if include_space:
                k.setMode('s', True)
            self.converter = k.getConverter()
            self.__initialized = True

    def romanize(self, text):
        return self.converter.do(text)

    @classmethod
    def romanizers(cls, include_space=False):
        try:
            roman_vals = kakasi._roman_vals
        except AttributeError as e:
            raise RuntimeError('Missing required package: pykakasi') from e
        for mode in roman_vals:
            yield J2R(mode, include_space=include_space)


def romanized_permutations(text: str, include_space=False) -> List[str]:
    if contains_hangul(text):
        return hangul_romanized_permutations(text, include_space=include_space)
    return [j2r.romanize(text) for j2r in J2R.romanizers(include_space)]


def matches_permutation(eng: str, cjk: str) -> bool:
    if not LangCat.matches(eng, LangCat.ENG) and LangCat.matches(cjk, LangCat.ENG):
        eng, cjk = cjk, eng
    if contains_hangul(cjk):
        return matches_hangul_permutation(eng, cjk)

    lc_letters = set('abcdefghijklmnopqrstuvwxyz')
    lc_eng = ''.join(c for c in eng.lower() if c in lc_letters)
    return lc_eng in romanized_permutations(cjk, False)
