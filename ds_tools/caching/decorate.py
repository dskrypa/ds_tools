"""
A ``cached`` memoizing decorator and utilities that go with it.

The ``cached`` decorator here is based on the ``cached`` and ``cachedmethod`` decorators in the `cachetools` package,
but it combines them and adds additional locking and toggling features.

This module is only compatible with Python 3 due to the dependency on the `inspect` built-in module.

:author: Doug Skrypa
"""

import json
import logging
import os
import warnings
from contextlib import suppress
from datetime import datetime
from functools import update_wrapper, wraps
from inspect import Signature, Parameter
from operator import attrgetter
from threading import RLock

from wrapt import synchronized

from ..core.itertools import flatten_mapping
from ..core.introspection import split_arg_vals_with_defaults, insert_kwonly_arg
from .exceptions import CacheLockWarning

__all__ = ['cached', 'CacheKey', 'disk_cached']
log = logging.getLogger(__name__)


def cached(cache=True, *, key=None, lock=None, optional=None, default=True, method=False, key_lock=True, exc=False):
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
    :param str|bool optional: If truthy, a keyword-only argument will be injected in the wrapped function's
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
    :param bool exc: If True, catch, cache, and rethrow exceptions, otherwise let them propagate as they happen.  If the
      exception is too complex, unpickling from a DB-based cache may not be possible.
    :return: The decorated function / method
    """
    optional = 'use_cached' if optional is True else optional
    method = True if isinstance(cache, (attrgetter, str)) else method
    if lock is True:
        lock_type = RLock
    else:
        lock_type = type(lock)  # Note: this will be a problem for Multiprocessing locks, which expect a context in init

    if method:
        cache = attrgetter(cache) if isinstance(cache, str) else cache
        if lock and isinstance(lock, str):
            lock = attrgetter(lock)
    else:
        cache = {} if cache is True else cache
        lock = lock_type() if lock is True else lock

    if key is None:
        try:
            key = cache._get_default_key_func()
        except AttributeError:
            key = CacheKey.simple

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
                        val = c[k]
                    except KeyError:
                        pass    # key not found
                    else:
                        if isinstance(val, Exception) and exc:
                            raise val
                        return val

                try:
                    val = func(*args, **kwargs)
                except Exception as e:
                    if exc:
                        val = e
                    else:
                        raise e

                with suppress(ValueError):  # raised if the value is too large
                    c[k] = val

                if isinstance(val, Exception) and exc:
                    raise val
                return val
        else:
            key_locks = {}
            single_lock = all(
                (method, lock is not True, not callable(lock), hasattr(lock, 'acquire'), hasattr(lock, 'release'))
            )
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
                    with cache_lock:
                        try:
                            val = c[k]
                        except KeyError:
                            pass  # key not found
                        else:
                            if isinstance(val, Exception) and exc:
                                raise val
                            return val

                    if key_lock:
                        do_exec = False
                        with cache_lock:
                            klock = key_locks.get(k, None)
                            if klock is None:               # The func is not already being executed with these args
                                do_exec = True
                                klock = key_locks[k] = lock_type() if lock is not True else RLock()
                                # Acquire before releasing cache_lock to prevent the wrong thread from getting it first
                                klock.acquire()

                        if do_exec:
                            try:
                                try:
                                    val = func(*args, **kwargs)
                                except Exception as e:
                                    if exc:
                                        val = e
                                    else:
                                        raise e

                                with suppress(ValueError):  # raised if the value is too large
                                    with cache_lock:
                                        c[k] = val
                            finally:
                                with cache_lock:
                                    klock.release()
                                    del key_locks[k]  # Allow future runs if key disappears from cache (e.g., TTLCache)

                            if isinstance(val, Exception) and exc:
                                raise val
                            return val
                        else:
                            with klock:         # Block until the executing thread completes
                                with cache_lock:
                                    try:
                                        val = c[k]
                                    except KeyError:
                                        pass    # Just in case something goes wrong; falls thru to execute/store/return
                                    else:
                                        if isinstance(val, Exception) and exc:
                                            raise val
                                        return val
                try:
                    val = func(*args, **kwargs)
                except Exception as e:
                    if exc:
                        val = e
                    else:
                        raise e

                with suppress(ValueError):  # raised if the value is too large
                    with cache_lock:
                        c[k] = val

                if isinstance(val, Exception) and exc:
                    raise val
                return val
        wrapper = update_wrapper(wrapper, func)
        if optional:    # insert the param and docstring in the wrapper, not the original function
            new_param = Parameter(optional, Parameter.KEYWORD_ONLY, default=default)
            description = 'Use cached return values for previously used arguments if they exist'
            insert_kwonly_arg(wrapper, new_param, description, 'bool', sig=sig)
        return wrapper
    return decorator


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
                cache_file_base = '{}{}_{}_'.format(prefix, func.__name__, getuser())
            else:
                cache_file_base = '{}_{}_'.format(prefix, getuser())
            cache_file = cache_file_base + '{}.{}'.format(datetime.now().strftime(date_fmt), ext)
            cache_dir = os.path.dirname(cache_file)
            validate_or_make_dir(cache_dir, permissions=0o17777)

            existing_files = [os.path.join(cache_dir, file) for file in os.listdir(cache_dir)]
            with suppress(ValueError):
                existing_files.remove(cache_file)

            for file_path in fnmatch.filter(existing_files, cache_file_base + '*'):
                try:
                    if os.path.isfile(file_path):
                        log.debug('Deleting old cache file: {}'.format(file_path))
                        os.remove(file_path)
                except OSError as e:
                    log.debug('Error deleting old cache file {}: [{}] {}'.format(file_path, type(e).__name__, e))

            # Note: rb/wb and to_str/to_bytes are used below to handle reading/writing gzip files
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
    __slots__ = ('_hash', '_vals')

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
        return args if not kwargs else args + sum(sorted(kwargs.items()), (cls,))

    @classmethod
    def simple(cls, *args, **kwargs):
        """Return a cache key for the specified hashable arguments."""
        return cls(cls._to_tuple(*args, **kwargs))

    @classmethod
    def simple_noself(cls, *args, **kwargs):
        """Return a cache key for the specified hashable arguments, omitting the first positional argument."""
        return cls(cls._to_tuple(*args[1:], **kwargs))

    @classmethod
    def _sanitize_dict(cls, a_dict):
        a_dict = flatten_mapping(a_dict)
        return {key: tuple(value) if isinstance(value, list) else value for key, value in a_dict.items()}

    @classmethod
    def typed(cls, *args, **kwargs):
        """Return a typed cache key for the specified hashable arguments."""
        key = cls._to_tuple(*args, **kwargs)
        key += tuple(type(v) for v in args)
        key += tuple(type(v) for _, v in sorted(kwargs.items()))
        return cls(key)
