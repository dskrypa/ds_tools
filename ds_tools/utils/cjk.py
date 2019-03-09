#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging
import re
import string
import unicodedata

__all__ = [
    "is_hangul", "contains_hangul", "is_japanese", "contains_japanese", "is_cjk", "contains_cjk",
    "is_any_cjk", "contains_any_cjk", "is_hangul_syllable", "decompose_syllables"
]
log = logging.getLogger(__name__)

HANGUL_RANGES = [       # Source: https://en.wikipedia.org/wiki/Korean_language_and_computers#Hangul_in_Unicode
    (0xAC00, 0xD7A3),   # Hangul syllables
    (0x1100, 0x11FF),   # Hangul Jamo
    (0x3130, 0x318F),   # Hangul Compatibility Jamo
    (0xA960, 0xA97F),   # Hangul Jamo Extended-A
    (0xD7B0, 0xD7FF),   # Hangul Jamo Extended-B
    (0xFFA0, 0xFFDC),   # Halfwidth and Fullwidth Forms (Hangul)
]
CJK_RANGES = [          # Source: https://en.wikipedia.org/wiki/CJK_Unified_Ideographs
    (0x4E00, 0x9FFF),   # CJK Unified Ideographs
    (0x3400, 0x4DBF),   # CJK Unified Ideographs Extension A
    (0x20000, 0x2A6DF), # CJK Unified Ideographs Extension B
    (0x2A700, 0x2B73F), # CJK Unified Ideographs Extension C
    (0x2B740, 0x2B81F), # CJK Unified Ideographs Extension D
    (0x2B820, 0x2CEAF), # CJK Unified Ideographs Extension E
    (0x2CEB0, 0x2EBEF), # CJK Unified Ideographs Extension F
    (0x2E80, 0x2EFF),   # CJK Radicals Supplement
    (0x2F00, 0x2FDF),   # Kangxi Radicals
    (0x2FF0, 0x2FFF),   # Ideographic Description Characters
    (0x3000, 0x303F),   # CJK Symbols and Punctuation
    (0x31C0, 0x31EF),   # CJK Strokes
    (0x3200, 0x32FF),   # Enclosed CJK Letters and Months
    (0x3300, 0x33FF),   # CJK Compatibility
    (0xF900, 0xFAFF),   # CJK Compatibility Ideographs
    (0xFE30, 0xFE4F),   # CJK Compatibility Forms
    (0x1F200, 0x1F2FF), # Enclosed Ideographic Supplement
    (0x2F800, 0x2FA1F), # CJK Compatibility Ideographs Supplement
]
KATAKANA_RANGES = [     # Source: https://en.wikipedia.org/wiki/Katakana#Unicode
    (0x30A0, 0x30FF),   # Katakana
    (0xFF65, 0xFF9F),   # Halfwidth and Fullwidth Forms (Katakana)
    (0x32D0, 0x32FE),   # Enclosed CJK Letters and Months (Katakana)
    (0x31F0, 0x31FF),   # Katakana Phonetic Extensions
    (0x1B000, 0x1B0FF), # Kana Supplement
    (0x3099, 0x3099),   # COMBINING KATAKANA-HIRAGANA VOICED SOUND MARK (non-spacing dakuten)
    (0x309A, 0x309C),   # (sound marks)
    (0x1F201, 0x1F202), # SQUARED KATAKANA KOKO, SA
    (0x1F213, 0x1F213), # SQUARED KATAKANA DE
]
HIRAGANA_RANGES = [     # Source: https://en.wikipedia.org/wiki/Hiragana#Unicode
    (0x3040, 0x309F),   # Hiragana
    (0x1B100, 0x1B120), # Kana Extended-A
]
# The following are not technically considered CJK, but will be for the purposes of this library
THAI_RANGES = [         # Source: https://en.wikipedia.org/wiki/Thai_alphabet#Unicode
    (0x0E00, 0x0E7F)    # Thai
]
JAPANESE_RANGES = KATAKANA_RANGES + HIRAGANA_RANGES
ANY_CJK_RANGES = HANGUL_RANGES + JAPANESE_RANGES + CJK_RANGES + THAI_RANGES
# https://en.wikipedia.org/wiki/Hangul_Compatibility_Jamo
JAMO_CONSONANTS_START = 0x3130
JAMO_VOWELS_START = 0x314F
JAMO_VOWELS_END = 0x3163
# The 0x3130 - 0x314E block contains both leading and final consonants - offsets from 0x3130 of lead consonants:
JAMO_LEAD_OFFSETS = [1, 2, 4, 7, 8, 9, 17, 18, 19, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30]
# There are 3 chars that may not be used as a final consonant:
JAMO_END_OFFSETS = [i for i in range(31) if i not in (8, 19, 25)]
SYLLABLES_START, SYLLABLES_END = HANGUL_RANGES[0]

NUM_STRIP_TBL = str.maketrans({c: "" for c in "0123456789"})
PUNC_STRIP_TBL = str.maketrans({c: "" for c in string.punctuation})


def is_hangul(a_str):
    """
    :param str a_str: A string
    :return bool: True if the given string contains only hangul characters, False otherwise.  Punctuation and spaces are
      ignored
    """
    if len(a_str) < 1:
        return False
    elif len(a_str) > 1:
        a_str = re.sub("\s+", "", a_str).translate(PUNC_STRIP_TBL)
        if len(a_str) < 1:
            return False
        return all(is_hangul(c) for c in a_str)

    as_dec = ord(a_str)
    return any(a <= as_dec <= b for a, b in HANGUL_RANGES)


def is_japanese(a_str):
    if len(a_str) < 1:
        return False
    elif len(a_str) > 1:
        a_str = re.sub("\s+", "", a_str).translate(PUNC_STRIP_TBL)
        if len(a_str) < 1:
            return False
        return all(is_japanese(c) for c in a_str)

    as_dec = ord(a_str)
    return any(a <= as_dec <= b for a, b in JAPANESE_RANGES)


def is_cjk(a_str):
    if len(a_str) < 1:
        return False
    elif len(a_str) > 1:
        a_str = re.sub("\s+", "", a_str).translate(PUNC_STRIP_TBL)
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
        a_str = re.sub("\s+", "", a_str)
        if strip_punc:
            a_str = a_str.translate(PUNC_STRIP_TBL)
        if strip_nums:
            a_str = a_str.translate(NUM_STRIP_TBL)
        if len(a_str) < 1:
            return False
        return all(is_any_cjk(c) for c in a_str)

    as_dec = ord(a_str)
    return any(a <= as_dec <= b for a, b in ANY_CJK_RANGES)


def is_hangul_syllable(char):
    if len(char) != 1:
        return False
    return SYLLABLES_START <= ord(char) <= SYLLABLES_END


def is_jamo(char):
    if len(char) != 1:
        return False
    return JAMO_CONSONANTS_START < ord(char) <= JAMO_VOWELS_END


def is_lead_jamo(char):
    if len(char) != 1:
        return False
    return (ord(char) - JAMO_CONSONANTS_START) in JAMO_LEAD_OFFSETS


def is_vowel_jamo(char):
    if len(char) != 1:
        return False
    return JAMO_VOWELS_START <= ord(char) <= JAMO_VOWELS_END


def is_final_jamo(char):
    if len(char) != 1:
        return False
    return (ord(char) - JAMO_CONSONANTS_START) in JAMO_END_OFFSETS


def decompose_syllables(a_str):
    """
    Formula from: https://en.wikipedia.org/wiki/Korean_language_and_computers#Hangul_Syllables_block

    :param str a_str: A string
    :return str: The provided string with all hangul syllables decomposed to jamo
    """
    if len(a_str) > 1:
        return "".join(decompose_syllables(c) for c in a_str)
    elif not is_hangul_syllable(a_str):                     # This also handles len<1 case
        return a_str

    # syllable = 588 initial + 28 medial + final + 44032
    i, rem = divmod(ord(a_str) - 44032, 588)
    m, f = divmod(rem, 28)
    jamo = (
        chr(JAMO_CONSONANTS_START + JAMO_LEAD_OFFSETS[i]),
        chr(JAMO_VOWELS_START + m),
        chr(JAMO_CONSONANTS_START + JAMO_END_OFFSETS[f]) if f > 0 else ""
    )
    return "".join(jamo)


def compose_syllable(lead, vowel, final_consonant=""):
    """
    Composing 2/3 jamo into a single composed syllable is easy; composing a series of jamo into syllables is more
    difficult since some consonants may be used in the first or last position depending on other jamo in the series.

    :param char lead: Lead consonant jamo
    :param char vowel: Vowel jamo
    :param char final_consonant: Final consonant jamo
    :return char: A composed hangul syllable
    """
    initial = JAMO_LEAD_OFFSETS.index(ord(lead) - JAMO_CONSONANTS_START)
    medial = ord(vowel) - JAMO_VOWELS_START
    final = 0 if not final_consonant else JAMO_END_OFFSETS.index(ord(final_consonant) - JAMO_CONSONANTS_START)
    return chr(44032 + (initial * 588) + (medial * 28) + final)


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
        log.info("{!r}: {}".format(c, unicodedata.name(c)))
