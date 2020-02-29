"""
:author: Doug Skrypa
"""

import re
from fnmatch import translate
from functools import lru_cache
from os.path import normcase
from posixpath import normcase as posix_normcase

__all__ = ['fnmatches', 'any_fnmatches', 'FnMatcher']


def fnmatches(iterable, pat, ignore_case=False):
    """Generator version of fnmatch.filter, with added support for ignoring case"""
    match = _compile_pattern(normcase(pat), ignore_case=ignore_case)
    if normcase is posix_normcase:
        # normcase on posix is NOP. Optimize it away from the loop.
        for value in iterable:
            if match(value):
                yield value
    else:
        for value in iterable:
            if match(normcase(value)):
                yield value


def any_fnmatches(iterable, pat, ignore_case=False):
    """Version of fnmatch.filter that returns True if any of the provided values match"""
    match = _compile_pattern(normcase(pat), ignore_case=ignore_case)
    if normcase is posix_normcase:
        # normcase on posix is NOP. Optimize it away from the loop.
        return any(match(value) for value in iterable)
    else:
        return any(match(normcase(value)) for value in iterable)


class FnMatcher:
    _use_normcase = normcase is not posix_normcase

    def __init__(self, patterns, ignore_case=False):
        if isinstance(patterns, str):
            patterns = (patterns,)
        self.patterns = tuple(_compile_pattern(normcase(pat), ignore_case=ignore_case) for pat in patterns)

    def match(self, value):
        """
        :param str value: A string
        :return bool: True if the value matches any of this matcher's patterns
        """
        if self._use_normcase:
            value = normcase(value)
        return any(pat(value) for pat in self.patterns)

    def matches(self, values):
        """
        :param iterable values: An iterable that yields strings
        :return bool: True if any of the values match any of this matcher's patterns
        """
        if self._use_normcase:
            values = (normcase(val) for val in values)
        # The below order consumes values once
        return any(pat(val) for val in values for pat in self.patterns)


@lru_cache(maxsize=256, typed=True)
def _compile_pattern(pat, ignore_case=False):
    """Copied from fnmatch; modified to support ignoring case"""
    if isinstance(pat, bytes):
        pat_str = str(pat, 'ISO-8859-1')
        res_str = translate(pat_str)
        res = bytes(res_str, 'ISO-8859-1')
    else:
        res = translate(pat)

    if ignore_case:
        return re.compile(res, re.IGNORECASE).match
    return re.compile(res).match
