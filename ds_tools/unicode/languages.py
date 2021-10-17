"""
Tools for identifying the languages used in text.

:author: Doug Skrypa
"""

import logging
import re
import string
from collections import defaultdict
from enum import Enum
from typing import Union, Optional, Iterator, Iterable, Container

from cachetools import LRUCache
try:
    from pykakasi import Kakasi
except ImportError:
    Kakasi = None

from ..caching import cached
from ..core.decorate import classproperty
from ..utils.text_processing import chars_by_category, strip_punctuation
from .hangul import hangul_romanized_permutations, matches_hangul_permutation
from .ranges import LATIN_RANGES, GREEK_COPTIC_RANGES, CYRILLIC_RANGES, HANGUL_RANGES, CJK_RANGES
from .ranges import THAI_RANGES, JAPANESE_RANGES, NON_ENG_RANGES

__all__ = [
    'is_hangul', 'contains_hangul', 'is_japanese', 'contains_japanese', 'is_cjk', 'contains_cjk',
    'is_any_cjk', 'contains_any_cjk', 'LangCat', 'romanized_permutations', 'matches_permutation'
]
log = logging.getLogger(__name__)

LANG_CAT_NAMES = ['NULL', 'MIX', 'English', 'Korean', 'Japanese', 'Chinese', 'Thai', 'Greek', 'Cyrillic', 'UNKNOWN']


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

    def __lt__(self, other: 'LangCat') -> bool:
        return self.value < other.value

    @classproperty
    def non_eng_cats(self) -> tuple['LangCat', ...]:
        return LangCat.UNK, LangCat.HAN, LangCat.JPN, LangCat.CJK, LangCat.THAI, LangCat.GRK, LangCat.CYR

    @classproperty
    def asian_cats(self) -> tuple['LangCat', ...]:
        return LangCat.HAN, LangCat.JPN, LangCat.CJK, LangCat.THAI

    asian = asian_cats

    @classmethod
    def _ranges(cls) -> Iterator[tuple['LangCat', list[tuple[int, int]]]]:
        yield cls.ENG, LATIN_RANGES
        yield cls.HAN, HANGUL_RANGES
        yield cls.JPN, JAPANESE_RANGES
        yield cls.THAI, THAI_RANGES
        yield cls.CJK, CJK_RANGES
        yield cls.GRK, GREEK_COPTIC_RANGES
        yield cls.CYR, CYRILLIC_RANGES

    @classmethod
    @cached(LRUCache(200), exc=True)
    def categorize(cls, text: Optional[str], detailed: bool = False) -> Union['LangCat', set['LangCat']]:
        if not text:
            return {cls.NUL} if detailed else cls.NUL
        elif detailed:
            text = _strip_non_word_chars(text)
            return set(cls.categorize(c) for c in text) if text else {cls.NUL}
        elif len(text) == 1:
            dec = ord(text)
            for cat, ranges in cls._ranges():
                if any(a <= dec <= b for a, b in ranges):
                    return cat
            return cls.UNK
        else:
            if text := _strip_non_word_chars(text):
                cat = cls.categorize(text[0])
                for c in text[1:]:
                    if cls.categorize(c) != cat:
                        return cls.MIX
                return cat
            return cls.NUL

    @classmethod
    def categorize_all(cls, texts: Iterable[Optional[str]], detailed: bool = False) -> tuple['LangCat', ...]:
        return tuple(cls.categorize(t, detailed) for t in texts)

    @classmethod
    @cached(LRUCache(200), exc=True)
    def matches(cls, text: Optional[str], *cats: 'LangCat', detailed: bool = False) -> bool:
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
        :param text: Text to examine
        :param cat: One or more :class:`LangCat` language categories
        :return: True if the given text contains a character with the given language category, False otherwise
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
            raise ValueError(f'{cat!r} is not supported for {cls.__name__}.contains_any_not()')
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
        if lang in {'english', 'eng', 'en', 'spanish'}:     # A better enum value would have been latin, since this is
            return cls.ENG                                  # more about unicode than actual language
        elif lang in {'korean', 'hangul', 'kor', 'kr', 'ko'}:
            return cls.HAN
        elif lang in {'japanese', 'jp', 'jpn', 'jap'}:
            return cls.JPN
        elif lang == 'thai':
            return cls.THAI
        elif lang in {'chinese', 'mandarin', 'chn'}:
            return cls.CJK
        elif lang in {'russian'}:
            return cls.CYR
        elif lang in {'greek'}:
            return cls.GRK
        return cls.UNK

    @classmethod
    def split(cls, text: str, strip: bool = True) -> list[str]:
        if strip:
            text = text.strip()
        if not text:
            return []

        indexes = []
        last = None
        last_char = None
        i = 0
        for c in text:
            if _is_punc_or_symbol(c):
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

        # log.debug(f'indexes: {indexes}')
        parts = []
        for idx in indexes:
            part, rem = text[:idx], text[idx:]
            # log.debug(f'{idx=}, {part=}, {rem=}')
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


def _is_punc_or_symbol(char: str) -> bool:
    try:
        all_punc_sym_ws = _is_punc_or_symbol._all_punc_sym_ws
    except AttributeError:
        all_punc_sym_ws = _is_punc_or_symbol._all_punc_sym_ws = chars_by_category(prefix=('P', 'S')) + string.whitespace
    return char in all_punc_sym_ws


def _strip_non_word_chars(text: str) -> str:
    if not text:
        return text
    try:
        sub = _strip_non_word_chars._sub
        table = _strip_non_word_chars._table
    except AttributeError:
        sub = _strip_non_word_chars._sub = re.compile(r'[\d\s]+').sub
        table = _strip_non_word_chars._table = str.maketrans({c: '' for c in chars_by_category(prefix=('P', 'S'))})
    # original = text
    text = sub('', text).translate(table)
    # log.debug(b'_strip_non_word_chars({original!r}) => {text!r}')
    return text


# region String Unicode Range Analysis


def is_hangul(a_str: str) -> bool:
    """
    :param a_str: A string
    :return: True if the string contains only hangul characters, False otherwise.  Punctuation and spaces are ignored.
    """
    if (str_len := len(a_str)) < 1:
        return False
    elif str_len > 1:
        a_str = strip_punctuation(a_str)
        if len(a_str) < 1:
            return False
        return all(is_hangul(c) for c in a_str)

    as_dec = ord(a_str)
    return any(a <= as_dec <= b for a, b in HANGUL_RANGES)


def is_japanese(a_str: str) -> bool:
    if (str_len := len(a_str)) < 1:
        return False
    elif str_len > 1:
        a_str = strip_punctuation(a_str)
        if len(a_str) < 1:
            return False
        return all(is_japanese(c) for c in a_str)

    as_dec = ord(a_str)
    return any(a <= as_dec <= b for a, b in JAPANESE_RANGES)


def is_cjk(a_str: str) -> bool:
    if (str_len := len(a_str)) < 1:
        return False
    elif str_len > 1:
        a_str = strip_punctuation(a_str)
        if len(a_str) < 1:
            return False
        return all(is_cjk(c) for c in a_str)

    as_dec = ord(a_str)
    return any(a <= as_dec <= b for a, b in CJK_RANGES)


def is_any_cjk(a_str: str, strip_punc: bool = True, strip_nums: bool = True) -> bool:
    """
    :param a_str: A string
    :param strip_punc: True (default) to strip punctuation before processing when len > 1
    :param strip_nums: True (default) to strip numbers before processing when len > 1
    :return: True if the given string contains only CJK/Katakana/Hiragana/Hangul characters (ignoring spaces,
      and optionally ignoring punctuation and numbers)
    """
    if (str_len := len(a_str)) < 1:
        return False
    elif str_len > 1:
        if strip_punc:
            a_str = strip_punctuation(a_str)
        else:
            try:
                sub = is_any_cjk._sub
            except AttributeError:
                sub = is_any_cjk._sub = re.compile(r'\s+').sub
            a_str = sub('', a_str)  # strip_punctuation also strips spaces

        if strip_nums:
            try:
                table = is_any_cjk._table
            except AttributeError:
                table = is_any_cjk._table = str.maketrans({c: '' for c in '0123456789'})
            a_str = a_str.translate(table)

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


# endregion


class J2R:
    __instance = None

    def __new__(cls):
        if cls.__instance is None:
            cls.__instance = super().__new__(cls)
        return cls.__instance

    def __init__(self):
        if not hasattr(self, 'kakasi'):
            try:
                self.kakasi = Kakasi()
            except TypeError as e:
                raise RuntimeError('Missing required package: pykakasi') from e

    def romanize(self, text: str, include_space: bool = False) -> Iterator[str]:
        parts = defaultdict(list)
        skip = {'orig', 'hira', 'kana'}
        for convert_dict in self.kakasi.convert(text):
            for conv_type, converted in convert_dict.items():
                if conv_type not in skip:
                    parts[conv_type].append(converted)
        join_str = ' ' if include_space else ''
        for group in parts.values():
            yield join_str.join(group)


def romanized_permutations(text: str, include_space: bool = False) -> set[str]:
    if contains_hangul(text):
        return hangul_romanized_permutations(text, include_space=include_space)
    return set(J2R().romanize(text, include_space))


def matches_permutation(eng: str, cjk: str) -> bool:
    if not LangCat.matches(eng, LangCat.ENG) and LangCat.matches(cjk, LangCat.ENG):
        eng, cjk = cjk, eng
    if contains_hangul(cjk):
        return matches_hangul_permutation(eng, cjk)

    lc_letters = set('abcdefghijklmnopqrstuvwxyz')
    lc_eng = ''.join(c for c in eng.lower() if c in lc_letters)
    return lc_eng in romanized_permutations(cjk, False)


def _print_unicode_names(a_str: str):
    import unicodedata
    for c in a_str:
        log.info('{!r}: {}'.format(c, unicodedata.name(c)))
