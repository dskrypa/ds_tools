#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging
import re
import string
import unicodedata

__all__ = ["is_hangul", "contains_hangul", "is_hangul_syllable", "decompose_syllables"]
log = logging.getLogger("ds_tools.utils.unicode")

HANGUL_RANGES = [       # Source: https://en.wikipedia.org/wiki/Korean_language_and_computers#Hangul_in_Unicode
    (0xAC00, 0xD7A3),   # Hangul syllables
    (0x1100, 0x11FF),   # Hangul Jamo
    (0x3130, 0x318F),   # Hangul Compatibility Jamo
    (0xA960, 0xA97F),   # Hangul Jamo Extended-A
    (0xD7B0, 0xD7FF)    # Hangul Jamo Extended-B
]
# https://en.wikipedia.org/wiki/Hangul_Compatibility_Jamo
JAMO_CONSONANTS_START = 0x3130
JAMO_VOWELS_START = 0x314F
JAMO_VOWELS_END = 0x3163
# The 0x3130 - 0x314E block contains both leading and final consonants - offsets from 0x3130 of lead consonants:
JAMO_LEAD_OFFSETS = [1, 2, 4, 7, 8, 9, 17, 18, 19, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30]
# There are 3 chars that may not be used as a final consonant:
JAMO_END_OFFSETS = [i for i in range(31) if i not in (8, 19, 25)]
PUNC_STRIP_TBL = str.maketrans({c: "" for c in string.punctuation})
SYLLABLES_START, SYLLABLES_END = HANGUL_RANGES[0]


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


def _print_unicode_names(a_str):
    for c in a_str:
        log.info("{!r}: {}".format(c, unicodedata.name(c)))
