"""
Helpers for matching strings against glob/fnmatch patterns, or regex patterns.

Improves on the fnmatch stdlib module by compiling the glob->regex pattern once, then reusing it to match multiple
strings.

:author: Doug Skrypa
"""

import re
from abc import ABC, abstractmethod
from fnmatch import translate
from functools import lru_cache
from os.path import normcase
from posixpath import normcase as posix_normcase
from typing import Iterable, Iterator, Union, Match, Callable, Optional

__all__ = ['fnmatches', 'any_fnmatches', 'PatternMatcher', 'FnMatcher', 'ReMatcher']

MatchFunc = Callable[[str], Optional[Match]]
Strings = Iterable[str]


def fnmatches(iterable: Strings, pat: str, ignore_case: bool = False) -> Iterator[str]:
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


def any_fnmatches(iterable: Strings, pat: str, ignore_case: bool = False) -> bool:
    """Version of fnmatch.filter that returns True if any of the provided values match"""
    match = _compile_pattern(normcase(pat), ignore_case=ignore_case)
    if normcase is posix_normcase:
        # normcase on posix is NOP. Optimize it away from the loop.
        return any(match(value) for value in iterable)
    else:
        return any(match(normcase(value)) for value in iterable)


class PatternMatcher(ABC):
    __slots__ = ('patterns',)
    patterns: tuple[MatchFunc, ...]

    @abstractmethod
    def match(self, value: str) -> bool:
        raise NotImplementedError

    @abstractmethod
    def matches(self, values: Strings) -> bool:
        raise NotImplementedError

    @abstractmethod
    def matching_values(self, values: Strings) -> Iterator[str]:
        raise NotImplementedError


class FnMatcher(PatternMatcher):
    __slots__ = ()
    _use_normcase = normcase is not posix_normcase

    def __init__(self, patterns: Union[str, Strings], ignore_case: bool = False):
        if isinstance(patterns, str):
            patterns = (patterns,)
        self.patterns = tuple(_compile_pattern(normcase(pat), ignore_case=ignore_case) for pat in patterns)

    def match(self, value: str) -> bool:
        """
        :param value: A string
        :return: True if the value matches any of this matcher's patterns
        """
        if self._use_normcase:
            value = normcase(value)
        return any(pat(value) for pat in self.patterns)

    def matches(self, values: Strings) -> bool:
        """
        :param values: An iterable that yields strings
        :return: True if any of the values match any of this matcher's patterns
        """
        if self._use_normcase:
            values = (normcase(val) for val in values)
        # The below order consumes values once
        return any(pat(val) for val in values for pat in self.patterns)

    def matching_values(self, values: Strings) -> Iterator[str]:
        if self._use_normcase:
            values = map(normcase, values)
        patterns = self.patterns
        for value in values:
            if any(pat(value) for pat in patterns):
                yield value


class ReMatcher(PatternMatcher):
    __slots__ = ()

    def __init__(self, patterns: Union[str, Strings], ignore_case: bool = False):
        if isinstance(patterns, str):
            patterns = (patterns,)
        self.patterns = tuple(
            re.compile(pat, re.IGNORECASE).match if ignore_case else re.compile(pat).match for pat in patterns
        )

    def match(self, value: str) -> bool:
        """
        :param value: A string
        :return: True if the value matches any of this matcher's patterns
        """
        return any(pat(value) for pat in self.patterns)

    def matches(self, values: Strings) -> bool:
        """
        :param values: An iterable that yields strings
        :return: True if any of the values match any of this matcher's patterns
        """
        # The below order consumes values once
        return any(pat(val) for val in values for pat in self.patterns)

    def matching_values(self, values: Strings) -> Iterator[str]:
        patterns = self.patterns
        for value in values:
            if any(pat(value) for pat in patterns):
                yield value


@lru_cache(maxsize=256, typed=True)
def _compile_pattern(pat: Union[bytes, str], ignore_case: bool = False) -> MatchFunc:
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
