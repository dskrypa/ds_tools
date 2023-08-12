"""
A ``cached`` memoizing decorator and utilities that go with it.

The ``cached`` decorator here is based on the ``cached`` and ``cachedmethod`` decorators in the `cachetools` package,
but it combines them and adds additional locking and toggling features.

This module is only compatible with Python 3 due to the dependency on the `inspect` built-in module.

:author: Doug Skrypa
"""

from __future__ import annotations

import json
import logging
import os
import warnings
from datetime import datetime
from functools import update_wrapper, wraps, partial
from inspect import Signature, Parameter
from operator import attrgetter
from threading import Lock, RLock
from typing import TypeVar, Union, Callable, MutableMapping, ParamSpec, Generic, Hashable

from ..core.itertools import flatten_mapping
from ..core.introspection import _split_arg_vals_with_defaults, insert_kwonly_arg

__all__ = ['cached', 'CacheKey', 'disk_cached', 'CacheLockWarning']
log = logging.getLogger(__name__)

P = ParamSpec('P')
T = TypeVar('T')
Obj = TypeVar('Obj')
Func = Callable[P, T] | classmethod
Cache = MutableMapping[Hashable, T | Exception]
CacheFactory = Callable[[Obj], Cache]
CacheArg = Union[Cache, attrgetter, CacheFactory, str, bool]
LockArg = Union[Lock, RLock, attrgetter, str, bool]
_NoValue = object()


def cached(
    cache: CacheArg = True,
    *,
    key: Callable[P, Hashable] = None,
    lock: LockArg = None,
    optional: str | bool = None,
    default: bool = True,
    method: bool = None,
    key_lock: bool = True,
    exc: bool = False,
) -> Callable[[Func], CachedFunc[P, T]]:
    def decorator(func: Func):
        if lock is not None and lock is not False:
            cls, kwargs = LockingCachedFunc, {'lock': lock, 'key_lock': key_lock}
        else:
            cls, kwargs = CachedFunc, {}
        return cls(func, cache, key=key, optional=optional, optional_default=default, method=method, exc=exc, **kwargs)
    return decorator


class CachedFunc(Generic[P, T]):
    __slots__ = ('func', 'sig', 'cache', 'key', 'optional', 'method', 'cls_method', 'exc', '__dict__')
    cache: Cache | CacheFactory

    def __init__(
        self,
        func: Func,
        cache: CacheArg = True,
        *,
        key: Callable[P, Hashable] = None,
        optional: Union[bool, str] = None,
        optional_default: bool = True,
        method: bool = None,
        exc: bool = False,
    ):
        if method is None:
            method = isinstance(cache, (attrgetter, str))
        if method:
            if isinstance(cache, str):
                cache = attrgetter(cache)
            elif not callable(cache):
                raise TypeError(
                    f'Invalid type={cache.__class__.__name__} for {cache=} with method=True - expected the name of'
                    ' an attribute, an operator.attrgetter, or another func/callable that accepts one argument and'
                    ' returns a mutable mapping to use as a cache'
                )
        elif cache is None or cache is True:
            cache = {}

        if key is None:
            try:
                key = cache._get_default_key_func()  # noqa
            except AttributeError:
                key = CacheKey.simple_noself if method else CacheKey.simple

        if isinstance(func, classmethod):
            self.cls_method = True  # It may be a class method without using an attrgetter for the cache or lock
            func = func.__func__
        else:
            self.cls_method = False
        self.func = func
        self.sig = Signature.from_callable(func)
        self.cache = cache
        self.key = key
        self.method = method
        self.exc = exc
        update_wrapper(self, func)
        if optional:
            self.optional = Optional(optional, optional_default)
            self.optional.inject_param(self)
        else:
            self.optional = None

    def __get__(self, instance, owner):
        if self.cls_method:
            instance = owner  # This imitates the behavior of classmethod.__get__
        elif instance is None:
            return self
        return partial(self.__call__, instance)

    def _get_cached_value(self, cache: Cache, key, default=_NoValue):
        try:
            val = cache[key]
        except KeyError:
            return default
        else:
            if self.exc and isinstance(val, Exception):
                raise val
            return val

    def __call__(self, *args: P.args, **kwargs: P.kwargs) -> T:
        # The key needs to be popped first, if potentially present, to prevent it from being passed if the cache is None
        use_cached = kwargs.pop(self.optional.key, self.optional.default) if self.optional else True
        if self.method:
            cache = self.cache(args[0])  # noqa  # args[0] is the wrapped method's `self` or `cls`
        else:
            cache = self.cache
        if cache is None:
            return self.func(*args, **kwargs)

        key_args, key_kwargs = _split_arg_vals_with_defaults(self.sig, args, kwargs)
        key = self.key(*key_args, **key_kwargs)
        if use_cached and (val := self._get_cached_value(cache, key)) is not _NoValue:
            return val

        try:
            val = self.func(*args, **kwargs)
        except Exception as e:
            if not self.exc:
                raise
            val = e
            should_raise = True
        else:
            should_raise = False

        try:
            cache[key] = val
        except ValueError:  # May be raised if the value is too large to store
            pass

        if should_raise:
            raise val
        return val


class LockingCachedFunc(CachedFunc):
    __slots__ = ('lock', 'key_lock', 'key_lock_type', 'key_locks')

    def __init__(
        self,
        func: Func,
        cache: CacheArg = True,
        lock: LockArg = True,
        *,
        key: Callable[P, Hashable] = None,
        optional: Union[bool, str] = None,
        optional_default: bool = True,
        method: bool = None,
        key_lock: bool = True,
        key_lock_type: Callable[[], Lock] = RLock,
        exc: bool = False,
    ):
        super().__init__(
            func, cache, key=key, optional=optional, optional_default=optional_default, method=method, exc=exc
        )
        if self.method:
            if isinstance(lock, str):
                lock = attrgetter(lock)
            elif lock is True:
                name = getattr(self.func, '__name__', 'cache')
                lock = partial(_get_or_create_lock, lock_attr_name=f'_cached__{name}_lock')
            elif not callable(lock) and hasattr(lock, 'acquire') and hasattr(lock, 'release'):
                warnings.warn(CacheLockWarning(func, lock))
                _lock = lock
                def lock(_): return _lock
        elif lock is True:
            lock = RLock()

        self.lock = lock
        self.key_lock = key_lock
        self.key_lock_type = key_lock_type
        self.key_locks = {}

    def _get_and_store_new_value(self, cache: Cache, key, args: P.args, kwargs: P.kwargs, cache_lock: Lock):
        try:
            val = self.func(*args, **kwargs)
        except Exception as e:
            if not self.exc:
                raise
            val = e
            should_raise = True
        else:
            should_raise = False

        with cache_lock:
            try:
                cache[key] = val
            except ValueError:  # May be raised if the value is too large to store
                pass

        if should_raise:
            raise val
        return val

    def __call__(self, *args: P.args, **kwargs: P.kwargs) -> T:
        # The key needs to be popped first, if potentially present, to prevent it from being passed if the cache is None
        use_cached = kwargs.pop(self.optional.key, self.optional.default) if self.optional else True
        if self.method:
            obj = args[0]  # self or cls
            cache = self.cache(obj)  # noqa
            cache_lock = self.lock(obj)
        else:
            cache, cache_lock = self.cache, self.lock

        if cache is None:
            return self.func(*args, **kwargs)

        key_args, key_kwargs = _split_arg_vals_with_defaults(self.sig, args, kwargs)
        key = self.key(*key_args, **key_kwargs)
        if use_cached:
            with cache_lock:
                if (val := self._get_cached_value(cache, key)) is not _NoValue:
                    return val

            if self.key_lock:
                if (val := self._get_key_locked_value(cache_lock, cache, key, args, kwargs)) is not _NoValue:
                    return val
                # Something went wrong - fall back to calling the func here

        return self._get_and_store_new_value(cache, key, args, kwargs, cache_lock)

    def _get_key_locked_value(self, cache_lock: Lock, cache: Cache, key, args: P.args, kwargs: P.kwargs):
        wait = True
        with cache_lock:
            # Another thread technically may have just stored a value, and this thread may have acquired this lock
            # between the block where this method stores a new value and the finally where the key lock is deleted,
            # so another attempt to retrieve a cached value is needed.
            if (val := self._get_cached_value(cache, key)) is not _NoValue:
                return val
            # If a key_lock for this key already exists, then another thread is already calling the func with these
            # args to obtain a new value, so this thread should wait for that value to be available in the cache.
            if (key_lock := self.key_locks.get(key)) is None:
                wait = False  # The func isn't already being called with these args
                self.key_locks[key] = key_lock = self.key_lock_type()
                # Acquire before releasing cache_lock to prevent the wrong thread from getting it first
                key_lock.acquire()

        if wait:
            # A key_lock for these args already existed, so this thread should wait for the one calling the func with
            # the same args to store the result in the cache.  The cache_lock must be acquired after the key_lock,
            # otherwise the thread calling the func would be blocked from storing the result (due to deadlock).
            with key_lock, cache_lock:
                return self._get_cached_value(cache, key)

        # The key lock was already acquired, and we are in the first thread to call the func with these args
        try:
            return self._get_and_store_new_value(cache, key, args, kwargs, cache_lock)
        finally:
            with cache_lock:
                key_lock.release()
                # There are multiple cases where the function may need to be called again with the same args, such as
                # if the func raised an exception when exceptions are not configured to be stored, or if the cache is
                # a TTLCache or LRU cache or similar and the key naturally expired.  Deleting the key from key_locks
                # is the easiest way to track that a call with these args is complete - it avoids needing to track
                # whether a call is in progress some other way, and it has the added benefit of preventing a memory
                # leak due to holding on to keys for potentially thousands of args that are no longer relevant.
                del self.key_locks[key]
                # This code will only be reached if key_locks[key] was None at the beginning of this method, and no
                # cached value existed for this key / these args.
                # Since a value has now been stored, if another thread is waiting for cache_lock at the
                # top of this method, it will find a value and return without touching key_locks.
                # If no value was stored here for some reason, then that thread will create a new lock for this key.


class Optional:
    __slots__ = ('key', 'default')

    def __init__(self, key: str | bool, default: bool = True):
        self.key = 'use_cached' if key is True else key
        self.default = default

    def inject_param(self, wrapper: CachedFunc | LockingCachedFunc):
        new_param = Parameter(self.key, Parameter.KEYWORD_ONLY, default=self.default)
        description = 'Use cached return values for previously used arguments if they exist'
        insert_kwonly_arg(wrapper, new_param, description, 'bool', sig=wrapper.sig)


def disk_cached(prefix='/var/tmp/script_cache/', ext=None, date_fmt='%Y-%m-%d', compress=True):
    import fnmatch
    import gzip
    from getpass import getuser
    from ..core.serialization import PermissiveJSONEncoder
    from ..fs.paths import validate_or_make_dir

    open_func = gzip.open if compress else open
    ext = ext or ('json.gz' if compress else 'json')

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            if prefix.endswith('/'):
                cache_file_base = f'{prefix}{func.__name__}_{getuser()}_'
            else:
                cache_file_base = f'{prefix}_{getuser()}_'
            cache_file = cache_file_base + f'{datetime.now().strftime(date_fmt)}.{ext}'
            cache_dir = os.path.dirname(cache_file)
            validate_or_make_dir(cache_dir, permissions=0o17777)

            existing_files = [os.path.join(cache_dir, file) for file in os.listdir(cache_dir)]
            try:
                existing_files.remove(cache_file)
            except ValueError:
                pass

            for file_path in fnmatch.filter(existing_files, cache_file_base + '*'):
                try:
                    if os.path.isfile(file_path):
                        log.debug(f'Deleting old cache file: {file_path}')
                        os.remove(file_path)
                except OSError as e:
                    log.debug(f'Error deleting old cache file {file_path}: [{type(e).__name__}] {e}')

            # Note: rb/wb are used below to handle reading/writing gzip files
            if os.path.exists(cache_file):
                with open_func(cache_file, 'rb') as f:
                    return json.loads(f.read().decode('utf-8'))

            resp = func(*args, **kwargs)
            with open_func(cache_file, 'wb') as f:
                f.write(json.dumps(resp, indent=4, sort_keys=True, cls=PermissiveJSONEncoder).encode('utf-8'))
            return resp
        return wrapper
    return decorator


class CacheKey:
    """
    A key that can be used to represent hashable arguments to a function.

    After attempting to improve upon :class:`cachetools.keys._HashedTuple` by only storing the hash of the resulting
    tuple instead of holding additional references to the objects that were passed as arguments to the function that is
    using the ``@cached`` decorator, I realized that the __eq__ method also needed to be implemented, and only
    comparing hashes could result in a hash collision.  It is best to store the references to the original arguments.

    Keeping this class so that it can still be used with the :func:``CacheKey.simple`` and :func:``CacheKey.typed``
    class methods as constructors, and for the possibility of thinking of an alternate comparison method in the future.

    This class should not be instantiated directly - use the :func:`CacheKey.simple` and :func:`CacheKey.typed`
    classmethods as key functions.
    """
    __slots__ = ('_vals', '_hash')

    def __init__(self, tup):
        self._vals = tup
        self._hash = hash(tup)

    def __hash__(self) -> int:
        return self._hash

    def __eq__(self, other) -> bool:
        try:
            return self._vals == other._vals
        except AttributeError:
            return False

    @classmethod
    def simple(cls, *args, **kwargs):
        """Return a cache key for the specified hashable arguments."""
        return cls((args + sum(sorted(kwargs.items()), (cls,))) if kwargs else args)

    @classmethod
    def simple_noself(cls, *args, **kwargs):
        """Return a cache key for the specified hashable arguments, omitting the first positional argument."""
        return cls((args[1:] + sum(sorted(kwargs.items()), (cls,))) if kwargs else args[1:])

    @classmethod
    def _sanitize_dict(cls, a_dict):
        return {key: tuple(val) if isinstance(val, list) else val for key, val in flatten_mapping(a_dict).items()}

    @classmethod
    def typed(cls, *args, **kwargs):
        """Return a typed cache key for the specified hashable arguments."""
        if kwargs:
            sorted_kvs = sorted(kwargs.items())
            key = args + sum(sorted_kvs, (cls,)) + tuple(type(v) for v in args) + tuple(type(v) for _, v in sorted_kvs)
        else:
            key = args + tuple(type(v) for v in args)
        return cls(key)


_LOCK_ATTR_LOCK = RLock()


def _get_or_create_lock(obj, lock_attr_name: str = '_cached__cache_lock'):
    if (lock := vars(obj).get(lock_attr_name)) is None:
        with _LOCK_ATTR_LOCK:
            # In case two threads were trying to create this lock at
            # the same time, we need to check for its existence again
            if (lock := vars(obj).get(lock_attr_name)) is None:
                lock = RLock()
                setattr(obj, lock_attr_name, lock)

    return lock


class CacheLockWarning(Warning):
    def __init__(self, func, lock):
        self.func = func
        self.lock = lock

    def __str__(self) -> str:
        return (
            f'The @cached lock provided for method {self.func.__qualname__!r}'
            f' appears to be a single lock instance: {self.lock!r}'
        )
