"""
Classes that expand upon those in the built-in collections module.

:author: Doug Skrypa
"""

from collections import OrderedDict, Callable

__all__ = ['DefaultOrderedDict']


class DefaultOrderedDict(OrderedDict):
    def __init__(self, default_factory=None, *args, **kwargs):
        if (default_factory is not None) and (not isinstance(default_factory, Callable)):
            raise TypeError("first argument must be callable")
        OrderedDict.__init__(self, *args, **kwargs)
        self.default_factory = default_factory

    def __missing__(self, key):
        if self.default_factory is None:
            raise KeyError(key)
        self[key] = value = self.default_factory()
        return value

    def __reduce__(self):
        args = tuple() if self.default_factory is None else self.default_factory,
        return type(self), args, None, None, self.items()

    def copy(self):
        return self.__copy__()

    def __copy__(self):
        return type(self)(self.default_factory, self)
