"""
This module contains an implementation of ``cached_property`` for which the default behavior is to not block concurrent
access to the decorated method for separate instances of the class in which the method was defined.  The implementation
in the stdlib ``functools`` module behaves the way this implementation does when ``block_all`` is True.

Additional helpers are defined here for clearing the cached values so that they may be re-computed.
"""

from __future__ import annotations

import functools as _functools
from abc import ABC, abstractmethod
from contextlib import contextmanager
from functools import lru_cache
from threading import RLock
from types import GenericAlias
from typing import TypeVar, Union, Callable, Generic, MutableMapping, Collection, overload

__all__ = [
    'CachedProperty',
    'cached_property',
    'ClearableCachedProperty',
    'ClearableCachedPropertyMixin',
    'register_cached_property_class',
    'unregister_cached_property_class',
]

_NOT_FOUND = object()

T = TypeVar('T')
Obj = TypeVar('Obj')
Method = Callable[[Obj], T]
Cache = MutableMapping[str, T]


class CachedProperty(Generic[T]):
    def __init__(self, func: Method, block: bool = True, block_all: bool = False):
        """
        A lazy / cached property.  To reset the cached value, delete the key corresponding with the decorated method's
        name from its instance's ``__dict__``.

        :param func: The method for which results should be cached.
        :param block: If True (default), concurrent access attempts will be blocked separately for each target instance
          on which access is attempted.  If False (``block_all`` must also be False), then no lock will be used to
          prevent concurrent threads from calling the decorated method at the same time and both attempting to populate
          the cache with the results.  Ignored if ``block_all`` is True.
        :param block_all: If True, all concurrent access attempts will be blocked, regardless of the target instance on
          which the access is attempted (which matches the stdlib implementation).
        """
        self.func = func
        self.name = None
        self.__doc__ = func.__doc__
        self.lock = RLock()
        self.instance_locks = {}
        self.block = block
        self.block_all = block_all

    def __set_name__(self, owner, name: str):
        if (orig := self.name) is None:
            self.name = name
        elif orig != name:
            raise TypeError(
                f'Cannot assign the same {self.__class__.__name__} to two different names ({orig!r} and {name!r}).'
            )

    def get_name_and_cache(self, instance: Obj) -> tuple[str, Cache]:
        if (name := self.name) is None:
            raise TypeError(f'Cannot use {self.__class__.__name__} instance without calling __set_name__ on it.')

        try:
            cache = instance.__dict__
        except AttributeError:  # not all objects have __dict__ (e.g. class defines slots)
            cls = instance.__class__.__name__
            raise TypeError(f"Unable to cache {cls}.{name} because {cls} has no '__dict__' attribute") from None

        return name, cache

    def _get_instance_lock(self, key) -> RLock:
        with self.lock:
            try:
                return self.instance_locks[key]
            except KeyError:
                self.instance_locks[key] = lock = RLock()
                return lock

    @contextmanager
    def instance_lock(self, instance: Obj, owner):
        key = (id(owner), id(instance))
        # While the use of id() here is not ideal, the lifetime of the lock for this key should never exceed the
        # lifetime of the instance/class, and this allows un-hashable classes/instances to have cached properties.
        lock = self._get_instance_lock(key)
        lock.acquire()
        try:
            yield  # Re-try retrieval from cache & call the method, only blocking concurrent calls on this instance
        finally:
            lock.release()
            # Delete the entry in instance_locks because any other threads will already have been waiting for the lock
            # and any later accesses will get the value directly from the __dict__, bypassing __get__ entirely.
            with self.lock:
                try:
                    del self.instance_locks[key]
                except KeyError:  # An additional thread was waiting; most likely the first thread already deleted it
                    pass

    @overload
    def __get__(self, instance: None, owner) -> CachedProperty[T]:
        ...

    @overload
    def __get__(self, instance: Obj, owner) -> T:
        ...

    def __get__(self, instance, owner):
        if instance is None:
            return self

        name, cache = self.get_name_and_cache(instance)
        if (val := cache.get(name, _NOT_FOUND)) is _NOT_FOUND:
            if self.block:
                with self.instance_lock(instance, owner):
                    # check if another thread filled the cache while we waited for the lock
                    if (val := cache.get(name, _NOT_FOUND)) is _NOT_FOUND:
                        val = self.func(instance)
                        try:
                            cache[self.name] = val
                        except TypeError:
                            cls = instance.__class__.__name__
                            raise TypeError(
                                f'Unable to cache {cls}.{self.name} because {cls}.__dict__'
                                ' does not support item assignment'
                            ) from None
            else:
                val = self.func(instance)
                try:
                    cache[self.name] = val
                except TypeError:
                    cls = instance.__class__.__name__
                    raise TypeError(
                        f'Unable to cache {cls}.{self.name} because {cls}.__dict__ does not support item assignment'
                    ) from None

        return val

    __class_getitem__ = classmethod(GenericAlias)


def cached_property(
    func: Method = None, *, block: bool = True, block_all: bool = False
) -> Union[CachedProperty[T], Callable[[Method], CachedProperty[T]]]:
    if func is not None:
        return CachedProperty(func, block, block_all)

    def _cached_property(method: Method) -> CachedProperty[T]:
        return CachedProperty(method, block, block_all)

    return _cached_property


# region Clearable Cached Property


class ClearableCachedProperty(ABC):
    """
    Intended to be extended by descriptors that cache their computed value in the object instance's ``__dict__`` when
    that cached value can be safely deleted to trigger re-execution of the code that computes that value.
    """
    __slots__ = ()

    @abstractmethod
    def __get__(self, instance, owner):
        raise NotImplementedError


class ClearableCachedPropertyMixin:
    """
    Mixin for classes containing :class:`ClearableCachedProperty` descriptors and/or methods decorated with
    ``cached_property``.  Adds the :meth:`.clear_cached_properties` method to facilitate clearing all or specific
    cached values.
    """

    __slots__ = ()

    def clear_cached_properties(self, *names: str, skip: Collection[str] = None):
        """
        Purge the cached values for the cached properties with the specified names, or all cached properties that are
        present in this class if no names are specified.  Properties that did not have a cached value are ignored.

        :param names: The names of the cached properties to be cleared
        :param skip: A collection of names of cached properties that should NOT be cleared
        """
        clear_cached_properties(self, *names, skip=skip)


def get_cached_property_names(obj) -> set[str]:
    """Get the names of all cached properties that exist in the given object or class."""
    try:
        mro = type.mro(obj)
    except TypeError:
        obj = obj.__class__
        mro = type.mro(obj)

    return _get_cached_property_names(obj, tuple(mro[1:]))


@lru_cache(20)
def _get_cached_property_names(obj, mro) -> set[str]:
    names = {k for k, v in obj.__dict__.items() if is_cached_property(v)}
    for cls in mro:
        names |= get_cached_property_names(cls)

    return names


def clear_cached_properties(instance, *names: str, skip: Collection[str] = None):
    """
    Purge the cached values for the cached properties with the specified names, or all cached properties that are
    present in the given object if no names are specified.  Properties that did not have a cached value are ignored.

    :param instance: An object that contains cached properties
    :param names: The names of the cached properties to be cleared
    :param skip: A collection of names of cached properties that should NOT be cleared
    """
    if not names:
        names = get_cached_property_names(instance.__class__)
    if skip:
        if isinstance(skip, str):
            skip = (skip,)
        names = (name for name in names if name not in skip)

    cache = instance.__dict__
    for name in names:
        try:
            del cache[name]
        except KeyError:
            pass


_CACHED_PROPERTY_CLASSES: tuple[type, ...] = (CachedProperty, ClearableCachedProperty, _functools.cached_property)


def is_cached_property(obj) -> bool:
    return isinstance(obj, _CACHED_PROPERTY_CLASSES)


def register_cached_property_class(cls: type):
    global _CACHED_PROPERTY_CLASSES
    _CACHED_PROPERTY_CLASSES = (*_CACHED_PROPERTY_CLASSES, cls)


def unregister_cached_property_class(cls: type):
    global _CACHED_PROPERTY_CLASSES
    _CACHED_PROPERTY_CLASSES = tuple(c for c in _CACHED_PROPERTY_CLASSES if c is not cls)


# endregion
