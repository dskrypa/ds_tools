"""
Mixins for common functionality

:author: Doug Skrypa
"""

from typing import Optional
from weakref import finalize

__all__ = ['Finalizable']


class Finalizable:
    """
    Mixin to facilitate using :class:`weakref.finalize` with an explicit ``close`` method and context manager interface.

    Classes that include this mixin must store a :class:`weakref.finalize` object as ``self._finalizer``.

    Note::
        When initializing the :class:`weakref.finalize` object, it is important to ensure that func, args and kwargs do
        not own any references to obj, either directly or indirectly, since otherwise obj will never be garbage
        collected. In particular, func should not be a bound method of obj.

        You can find an example of :class:`weakref.finalize` being used correctly in `the stdlib tempfile module
        <https://github.com/python/cpython/blob/v3.10.4/Lib/tempfile.py#L782-L852>`_
    """
    _finalizer: finalize
    __close_attr: Optional[str] = None

    def __init_subclass__(cls, close_attr: str = None):
        if close_attr:
            cls.__close_attr = close_attr

    def close(self):
        try:
            obj, close_func, args, kwargs = self._finalizer.detach()
        except (TypeError, AttributeError):
            pass
        else:
            close_func(*args, **kwargs)
            if close_attr := self.__close_attr:
                try:
                    del self.__dict__[close_attr]
                except KeyError:
                    pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def __del__(self):
        self.close()
