"""
:author: Doug Skrypa
"""

import re
from itertools import product
from typing import Pattern, Sequence

from cachetools import LRUCache

from ...caching import cached
from .jamo import Word

__all__ = ['hangul_romanized_permutations_pattern', 'matches_hangul_permutation', 'hangul_romanized_permutations']


@cached(LRUCache(300))
def hangul_romanized_permutations_pattern(text: str, include_space: bool = False) -> Pattern:
    words = tuple(map(Word, text.split()))
    joiner = ' ' if include_space else ''
    pattern = joiner.join(
        word.romanization_pattern(prev=prev_word, next=next_word) for word, prev_word, next_word in _iter_words(words)
    )
    return re.compile(pattern, re.IGNORECASE)


def _iter_words(words: Sequence[Word]):
    last = len(words) - 1
    prev_word = None
    for i, word in enumerate(words):
        next_word = words[i + 1] if i < last else None
        yield word, prev_word, next_word
        prev_word = word


@cached(LRUCache(300))
def matches_hangul_permutation(eng: str, han: str) -> bool:
    lc_letters = set('abcdefghijklmnopqrstuvwxyz')
    lc_eng = ''.join(c for c in eng.lower() if c in lc_letters)
    return bool(hangul_romanized_permutations_pattern(han).match(lc_eng))


def hangul_romanized_permutations(text: str, include_space: bool = False) -> set[str]:
    words = tuple(map(Word, text.split()))
    joiner = ' ' if include_space else ''
    return set(map(joiner.join, product(*(word.romanizations for word in words))))
