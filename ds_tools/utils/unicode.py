#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging
import re
import string
import unicodedata

__all__ = ["is_hangul", "contains_hangul", "print_unicode_names", "strip_punctuation"]
log = logging.getLogger("ds_tools.utils.unicode")

HANGUL_RANGES = [       # Source: https://en.wikipedia.org/wiki/Korean_language_and_computers#Hangul_in_Unicode
    (0xAC00, 0xD7A3),   # Hangul syllables
    (0x1100, 0x11FF),   # Hangul Jamo
    (0x3130, 0x318F),   # Hangul Compatibility Jamo
    (0xA960, 0xA97F),   # Hangul Jamo Extended-A
    (0xD7B0, 0xD7FF)    # Hangul Jamo Extended-B
]
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


def contains_hangul(a_str):
    return any(is_hangul(c) for c in a_str)


def print_unicode_names(a_str):
    for c in a_str:
        log.info("{!r}: {}".format(c, unicodedata.name(c)))


def strip_punctuation(a_str):
    return re.sub("\s+", "", a_str).translate(PUNC_STRIP_TBL)
