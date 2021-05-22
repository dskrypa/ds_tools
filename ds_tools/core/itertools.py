"""
Functions that expand upon those in the built-in itertools module.

:author: Doug Skrypa
"""

from collections.abc import Mapping, MutableMapping
from copy import deepcopy
from itertools import chain, zip_longest
from typing import Iterable, Iterator

__all__ = ['chunked', 'flatten_mapping', 'itemfinder', 'kwmerge', 'merge', 'partitioned']


def itemfinder(iterable, func):
    """
    :param iterable: A collection of items
    :param func: Function that takes 1 argument and returns a bool
    :return: The first item in iterable for which func(item) evaluates to True, or None if no such item exists
    """
    for i in iterable:
        if func(i):
            return i


def chunked(seq, n):
    """Divide the given sequence into n roughly equal chunks"""
    chunk_size, remaining = divmod(len(seq), n)
    i = 0
    for c in range(n):
        j = i + chunk_size + (1 if remaining > 0 else 0)
        remaining -= 1
        yield seq[i:j]
        i = j


def partitioned(iterable: Iterable, n: int) -> Iterator[tuple]:
    """
    :param iterable: An iterable object
    :param n: The maximum number of elements in a given partition
    :return: Generator that yields tuples containing ``n`` elements from the given iterable.  The last tuple yielded
      will contain fewer than ``n`` elements if the total number of elements yielded by the iterable was not evenly
      divisible by ``n``.
    """
    _NotSet = object()
    args = [iter(iterable)] * n  # Each element is a ref to the same iterator, so zip will group up to n values
    zipper = iter(zip_longest(*args, fillvalue=_NotSet))
    try:
        last = next(zipper)
    except StopIteration:
        pass
    else:
        for part in zipper:
            yield last
            last = part

        yield tuple(ele for ele in last if ele is not _NotSet)


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


def nested_merge(a, b):
    """
    Merge the given dicts and any nested dicts that they contain.  Values from dict b will replace values from dict a if
    there is a key conflict on a value that is not a dict.
    """
    merged = deepcopy(a)
    for key, b_val in b.items():
        try:
            a_val = a[key]
        except KeyError:
            merged[key] = b_val
        else:
            if isinstance(a_val, MutableMapping) and isinstance(b_val, Mapping):
                merged[key] = nested_merge(a_val, b_val)
            else:
                merged[key] = b_val
    return merged


def nvmap(func, key, seq):
    """
    Nested Value Map.  For each item in the given sequence, apply the function to the value of item[key], then yield the
    item.
    """
    for val in seq:
        val[key] = func(val[key])
        yield val


def vmap(func, mapping):
    """Value Map.  Preserves the type of the original dict, and applies the function to each value in the given dict"""
    obj = type(mapping)()
    for k, v in mapping.items():
        obj[k] = func(v)
    return obj


def flatten_mapping(mapping, delimiter='.'):
    flattened = type(mapping)()
    for key, val in mapping.items():
        if isinstance(val, Mapping):
            for subkey, subval in flatten_mapping(val).items():
                flattened['{}{}{}'.format(key, delimiter, subkey)] = subval
        else:
            flattened[key] = val
    return flattened
