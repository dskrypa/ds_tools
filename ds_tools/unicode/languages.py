"""
Tools for identifying the languages used in text.

:author: Doug Skrypa
"""

import logging
import re
import string
import unicodedata
from enum import Enum

from cachetools import LRUCache

from ..caching import cached
from ..core import classproperty
from ..utils import ALL_PUNCTUATION, ALL_SYMBOLS
from .ranges import *

__all__ = [
    'is_hangul', 'contains_hangul', 'is_japanese', 'contains_japanese', 'is_cjk', 'contains_cjk',
    'is_any_cjk', 'contains_any_cjk', 'LangCat'
]
log = logging.getLogger(__name__)

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

    @classproperty
    def non_eng_cats(self):
        return LangCat.UNK, LangCat.HAN, LangCat.JPN, LangCat.CJK, LangCat.THAI, LangCat.GRK, LangCat.CYR

    @classproperty
    def asian_cats(self):
        return LangCat.HAN, LangCat.JPN, LangCat.CJK, LangCat.THAI

    @classmethod
    def _ranges(cls):
        yield cls.ENG, LATIN_RANGES
        yield cls.HAN, HANGUL_RANGES
        yield cls.JPN, JAPANESE_RANGES
        yield cls.THAI, THAI_RANGES
        yield cls.CJK, CJK_RANGES
        yield cls.GRK, GREEK_COPTIC_RANGES
        yield cls.CYR, CYRILLIC_RANGES

    @classmethod
    @cached(LRUCache(200), exc=True)
    def categorize(cls, text, detailed=False):
        if detailed:
            return set(cls.categorize(c) for c in text)
        elif len(text) == 1:
            dec = ord(text)
            for cat, ranges in cls._ranges():
                if any(a <= dec <= b for a, b in ranges):
                    return cat
            return cls.UNK
        elif len(text) == 0:
            return cls.NUL
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
    def contains_any(cls, text, cat):
        """
        :param str text: Text to examine
        :param LangCat cat: A :class:`LangCat` language category
        :return bool: True if the given text contains a character with the given language category, False otherwise
        """
        if cat == cls.MIX:
            return cls.categorize(text) == cls.MIX
        elif len(text) > 1:
            text = _strip_non_word_chars(text)
        if len(text) == 0:
            return cat == cls.NUL
        for c in text:
            if cls.categorize(c) == cat:
                return True
        return False

    @classmethod
    def contains_any_not(cls, text, cat):
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
    def for_name(cls, language):
        lang = language.lower()
        if lang in ('english', 'spanish'):
            return cls.ENG
        elif lang == 'korean':
            return cls.HAN
        elif lang == 'japanese':
            return cls.JPN
        elif lang == 'thai':
            return cls.THAI
        elif lang in ('chinese', 'mandarin'):
            return cls.CJK
        elif lang in ('russian',):
            return cls.CYR
        elif lang in ('greek',):
            return cls.GRK
        return cls.UNK


def _strip_non_word_chars(text):
    # original = text
    text = re.sub(r'[\d\s]+', '', text).translate(PUNC_SYMBOL_STRIP_TBL)
    # log.debug('_strip_non_word_chars({!r}) => {!r}'.format(original, text))
    return text


def is_hangul(a_str):
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


def is_japanese(a_str):
    if len(a_str) < 1:
        return False
    elif len(a_str) > 1:
        a_str = re.sub('\s+', '', a_str).translate(PUNC_STRIP_TBL)
        if len(a_str) < 1:
            return False
        return all(is_japanese(c) for c in a_str)

    as_dec = ord(a_str)
    return any(a <= as_dec <= b for a, b in JAPANESE_RANGES)


def is_cjk(a_str):
    if len(a_str) < 1:
        return False
    elif len(a_str) > 1:
        a_str = re.sub('\s+', '', a_str).translate(PUNC_STRIP_TBL)
        if len(a_str) < 1:
            return False
        return all(is_cjk(c) for c in a_str)

    as_dec = ord(a_str)
    return any(a <= as_dec <= b for a, b in CJK_RANGES)


def is_any_cjk(a_str, strip_punc=True, strip_nums=True):
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


def contains_hangul(a_str):
    return any(is_hangul(c) for c in a_str)


def contains_japanese(a_str):
    return any(is_japanese(c) for c in a_str)


def contains_cjk(a_str):
    return any(is_cjk(c) for c in a_str)


def contains_any_cjk(a_str):
    return any(is_any_cjk(c) for c in a_str)


def _print_unicode_names(a_str):
    for c in a_str:
        log.info('{!r}: {}'.format(c, unicodedata.name(c)))
