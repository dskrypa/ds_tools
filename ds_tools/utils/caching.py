#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
A ``cached`` memoizing decorator and utilities that go with it.

The ``cached`` decorator here is based on the ``cached`` and ``cachedmethod`` decorators in the `cachetools` package,
but it combines them and adds additional locking and toggling features.

This module is only compatible with Python 3 due to the dependency on the `inspect` built-in module.

:author: Doug Skrypa
"""

import gzip
import json
import os
import warnings
from contextlib import suppress
from functools import update_wrapper, wraps
from inspect import Signature, Parameter
from operator import attrgetter
from threading import RLock

from wrapt import synchronized

from .filesystem import validate_or_make_dir
from .introspection import split_arg_vals_with_defaults, insert_kwonly_arg
from .output import to_str, to_bytes
from .time import now

__all__ = ["cached", "CacheKey", "CacheLockWarning"]


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
    __slots__ = ("_hash", "_vals")
    _kwmark = (object(),)

    def __init__(self, tup):
        self._vals = tup
        self._hash = hash(tup)

    def __hash__(self):
        return self._hash

    def __eq__(self, other):
        try:
            return self._vals == other._vals
        except AttributeError:
            return False

    @classmethod
    def _to_tuple(cls, *args, **kwargs):
        if kwargs:
            return args + sum(sorted(kwargs.items()), cls._kwmark)
        else:
            return args

    @classmethod
    def simple(cls, *args, **kwargs):
        """Return a cache key for the specified hashable arguments."""
        return cls(cls._to_tuple(*args, **kwargs))

    @classmethod
    def typed(cls, *args, **kwargs):
        """Return a typed cache key for the specified hashable arguments."""
        key = cls._to_tuple(*args, **kwargs)
        key += tuple(type(v) for v in args)
        key += tuple(type(v) for _, v in sorted(kwargs.items()))
        return cls(key)


def is_lock(obj):
    """
    :param obj: An object
    :return bool: True if the object appears to be a lock instance, False otherwise
    """
    return hasattr(obj, "acquire") and hasattr(obj, "release")


def cached(cache=True, *, key=CacheKey.simple, lock=None, optional=None, default=True, method=False, key_lock=True):
    """
    A decorator to wrap a function / method with a memoizing callable that saves results in a cache.

    This unifies the :func:`cachetools.cached` and :func:`cachetools.cachedmethod` decorators to provide a single entry
    point and reduce code duplication.

    The default key function, :func:`CacheKey.simple`, does not store references to the values provided as function
    arguments.  The default values for arguments that were not provided are included during key generation to prevent
    re-computation when a default value is provided explicitly (or vice-versa).

    When using locking, if there are concurrent function calls with the same arguments before a cached value for those
    arguments exists, then only 1 thread/process is allowed to execute the function by default.  The ``key_lock``
    argument can be used to adjust this behavior.

    :param cache: The cache that will be used to store the wrapped function's results.  Behavior:
        - If the ``method`` argument is False (default), then this must be must be one of the following:
            - A container instance to be used as the cache
            - True (default) to use a dict as a cache
        - If the ``method`` argument is True, then this must be one of the following:
            - A callable that takes the first positional argument passed to the function (``self`` in the case of
                instance methods) and returns the container instance that should be used as the cache
            - A string that is the name of an attribute to use with :func:`operator.attrgetter` like the above option
        - If None, or the callable used when ``method`` is True returns None, then no caching will be used
    :param key: Function to convert the wrapped function's arguments to a cache key (default: :func:`CacheKey.simple`)
    :param lock: A threading/multiprocessing lock that will be used to protect read/write operations on the cache...
        - If None (default), no locking will be used
        - If the ``method`` argument is False (default), then this must be one of the following:
            - True to use :class:`threading.RLock`
            - Any other truthy value will be assumed to be a lock primitive that should be used
        - If the ``method`` argument is True, then this must be one of the following:
            - A callable that takes the first positional argument passed to the function (``self`` in the case of
                instance methods) and returns the lock instance that should be used
            - A string that is the name of an attribute to use with :func:`operator.attrgetter` like the above option
    :param str or bool optional: If truthy, a keyword-only argument will be injected in the wrapped function's
        signature to toggle caching.  If the provided value is ``True``, then a default argument name of ``use_cached``
        will be used.  If the provided value is a str, then that str will be used as the argument name.
    :param bool default: The default value of the argument used to toggle cache use when made optional via the
        ``optional`` argument (default: True)
    :param bool method: Indicate whether or not the wrapped function is a method, so the cache and lock should be
        retrieved from the object instance that the method belongs to (default: False).
    :param key_lock: Block concurrent function calls with the same arguments before a cached value for those arguments
        exists.  Concurrent function calls with different arguments will be allowed - this does not act as a lock for
        all executions of the wrapped function.  Only applies when the ``lock`` argument is used.  Behavior:
        - If True (default), then the same type of lock as the provided ``lock`` argument (or the type of lock returned
            when ``method`` is True) will be used.
        - If not truthy, then no key-based blocking will occur.
    :return: The decorated function / method
    """
    optional = "use_cached" if optional is True else optional
    if method:
        cache = attrgetter(cache) if isinstance(cache, str) else cache
        if lock:
            lock = attrgetter(lock) if isinstance(lock, str) else lock
    else:
        cache = {} if cache is True else cache
        if lock:
            lock = RLock() if lock is True else lock

    def decorator(func):
        sig = Signature.from_callable(func)
        if not lock:
            def wrapper(*args, **kwargs):
                use_cached = kwargs.pop(optional, default) if optional else True
                if method:
                    self = args[0]
                    c = cache(self)
                else:
                    c = cache

                if c is None:
                    return func(*args, **kwargs)

                kargs, kkwargs = split_arg_vals_with_defaults(sig, *args, **kwargs)
                k = key(*kargs, **kkwargs)
                if use_cached:
                    try:
                        return c[k]
                    except KeyError:
                        pass    # key not found

                v = func(*args, **kwargs)
                with suppress(ValueError):  # raised if the value is too large
                    c[k] = v
                return v
        else:
            key_locks = {}
            single_lock = all((method, lock is not True, not callable(lock), is_lock(lock)))
            if single_lock:
                warnings.warn(CacheLockWarning(func, lock))

            def wrapper(*args, **kwargs):
                use_cached = kwargs.pop(optional, default) if optional else True
                if method:
                    self = args[0]
                    c = cache(self)
                    if single_lock:
                        cache_lock = lock
                    else:
                        cache_lock = lock(self) if lock is not True else synchronized(self)
                else:
                    c = cache
                    cache_lock = lock

                if c is None:
                    return func(*args, **kwargs)

                kargs, kkwargs = split_arg_vals_with_defaults(sig, *args, **kwargs)
                k = key(*kargs, **kkwargs)
                if use_cached:
                    try:
                        with cache_lock:
                            return c[k]
                    except KeyError:
                        pass  # key not found

                    if key_lock:
                        do_exec = False
                        with cache_lock:
                            klock = key_locks.get(k, None)
                            if klock is None:               # The func is not already being executed with these args
                                do_exec = True
                                klock = key_locks[k] = type(cache_lock)() if lock is not True else RLock()
                                # Acquire before releasing cache_lock to prevent the wrong thread from getting it first
                                klock.acquire()

                        if do_exec:
                            try:
                                v = func(*args, **kwargs)
                                with suppress(ValueError):  # raised if the value is too large
                                    with cache_lock:
                                        c[k] = v
                            finally:
                                with cache_lock:
                                    klock.release()
                                    del key_locks[k] # Allow future runs if key disappears from cache (e.g., TTLCache)
                            return v
                        else:
                            try:
                                with klock:         # Block until the executing thread completes
                                    with cache_lock:
                                        return c[k]
                            except KeyError:    # Just in case something goes wrong; falls thru to execute/store/return
                                pass

                v = func(*args, **kwargs)
                with suppress(ValueError):  # raised if the value is too large
                    with cache_lock:
                        c[k] = v
                return v

        wrapper = update_wrapper(wrapper, func)
        if optional:
            new_param = Parameter(optional, Parameter.KEYWORD_ONLY, default=default)
            description = "Use cached return values for previously used arguments if they exist"
            insert_kwonly_arg(wrapper, new_param, description, "bool", sig=sig)
        return wrapper
    return decorator


def disk_cached(prefix="/var/tmp/script_cache/", ext=None, date_fmt="%Y-%m-%d", compress=True):
    open_func = gzip.open if compress else open
    ext = ext or ("json.gz" if compress else "json")

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            if prefix.endswith("/"):
                cache_file = "{}{}_{}.{}".format(prefix, func.__name__, now(date_fmt), ext)
            else:
                cache_file = "{}_{}.{}".format(prefix, now(date_fmt), ext)
            cache_dir = os.path.dirname(cache_file)
            validate_or_make_dir(cache_dir)

            if os.path.exists(cache_file):
                with open_func(cache_file, "rb") as f:
                    return json.loads(to_str(f.read()))

            resp = func(*args, **kwargs)
            with open_func(cache_file, "wb") as f:
                f.write(to_bytes(json.dumps(resp, indent=4, sort_keys=True)))
            return resp
        return wrapper
    return decorator


class CacheLockWarning(Warning):
    def __init__(self, func, lock):
        self.func = func
        self.lock = lock

    def __str__(self):
        msg_fmt = "The @cached lock provided for method '{}' appears to be a single lock instance: {}"
        return msg_fmt.format(self.func.__qualname__, self.lock)
