#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
:author: Doug Skrypa
"""

__all__ = ["replacement_itemgetter"]


class replacement_itemgetter:
    """
    Return a callable object that fetches the given item(s) from its operand.
    After f = itemgetter(2), the call f(r) returns r[2].
    After g = itemgetter(2, 5, 3), the call g(r) returns (r[2], r[5], r[3])
    """
    __slots__ = ("_items", "_call", "_repl")

    def __init__(self, item, *items, replacements=None):
        self._repl = replacements or {}
        if not items:
            self._items = (item,)
            def func(obj):
                val = obj[item]
                try:
                    return self._repl[val]
                except KeyError:
                    return val
            self._call = func
        else:
            self._items = items = (item,) + items
            def func(obj):
                vals = []
                for val in (obj[i] for i in items):
                    try:
                        vals.append(self._repl[val])
                    except KeyError:
                        vals.append(val)
                return tuple(vals)
            self._call = func

    def __call__(self, obj):
        return self._call(obj)
