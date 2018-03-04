#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
:author: Doug Skrypa
"""

from collections.abc import Mapping
from itertools import chain

__all__ = ["itemfinder", "partitioned", "kwmerge"]


def itemfinder(iterable, func):
    """
    :param iterable: A collection of items
    :param func: Function that takes 1 argument and returns a bool
    :return: The first item in iterable for which func(item) evaluates to True, or None if no such item exists
    """
    for i in iterable:
        if func(i):
            return i


def partitioned(seq, n):
    """
    :param seq: A :class:`collections.abc.Sequence` (i.e., list, tuple, set, etc.)
    :param int n: Max number of values in a given partition
    :return: Generator that yields sub-sequences of the given sequence with len being at most n
    """
    for i in range(0, len(seq), n):
        yield seq[i: i + n]


def kwmerge(*params, **kwargs):
    """
    Merge function parameters that may be None or a dict, skipping those that are None, into a dict.

    :param params: Dicts to merge
    :param kwargs: Key=value pairs to merge at the end
    :return dict: Merged values
    """
    merged = {}
    for p in chain(params, (kwargs,)):
        if p is not None:
            merged.update(p)
    return merged


def merge(*args, factory=None):
    """
    Merge a collection of dicts or other collections.abc.MutableMapping types by using `update`.  If no factory is
    specified and no args are provided, then an empty dict is returned.

    :param args: Collections to be merged via the `update` method of an instance of the factory
    :param factory: Keyword-only arg to specify the collection type to return (default: match type of first arg)
    :return: The result of calling factory() and running `update` on it with each provided arg
    """
    if not factory:
        if not args:
            return {}
        factory = type(args[0])
    merged = factory()
    for arg in args:
        merged.update(arg)
    return merged


def flatten_mapping(mapping, delimiter="."):
    flattened = type(mapping)()
    for key, val in mapping.items():
        if isinstance(val, Mapping):
            for subkey, subval in flatten_mapping(val).items():
                flattened["{}{}{}".format(key, delimiter, subkey)] = subval
        else:
            flattened[key] = val
    return flattened
