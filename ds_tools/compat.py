"""
Compatibility module.  Provides implementations of classes or functions that are not available in earlier versions of
Python.

:author: Doug Skrypa
"""

__all__ = ['cached_property']

try:
    from functools import cached_property   # Added in 3.8
except ImportError:
    class cached_property:
        """
        A decorator that converts a method into a lazy property.  The wrapped method id called the first time to
        retrieve the result, and then that calculated result is used the next time the value is accessed.  Deleting the
        attribute from the instance resets the cached value and will cause it to be re-computed.
        """
        def __init__(self, func):
            self.__doc__ = func.__doc__
            self.func = func

        def __get__(self, obj, cls):
            if obj is None:
                return self
            value = obj.__dict__[self.func.__name__] = self.func(obj)
            return value
