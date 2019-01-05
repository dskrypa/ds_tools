#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
A ``cached`` memoizing decorator and utilities that go with it.

The ``cached`` decorator here is based on the ``cached`` and ``cachedmethod`` decorators in the `cachetools` package,
but it combines them and adds additional locking and toggling features.

This module is only compatible with Python 3 due to the dependency on the `inspect` built-in module.

:author: Doug Skrypa
"""

import fnmatch
import gzip
import json
import logging
import os
import warnings
from contextlib import suppress
from functools import update_wrapper, wraps
from getpass import getuser
from inspect import Signature, Parameter
from operator import attrgetter
from threading import RLock
from urllib.parse import urlencode, quote as url_quote

from sqlalchemy import create_engine, MetaData, Table, Column, PickleType
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm.exc import NoResultFound
from sqlalchemy.exc import NoSuchTableError, OperationalError
from wrapt import synchronized

from .filesystem import validate_or_make_dir, get_user_cache_dir
from .introspection import split_arg_vals_with_defaults, insert_kwonly_arg
from .output import to_str, to_bytes, JSONSetEncoder
from .sql import ScopedSession
from .time import now

__all__ = ["cached", "CacheKey", "CacheLockWarning", "disk_cached", "DBCacheEntry", "DBCache", "FSCache"]
log = logging.getLogger("ds_tools.utils.caching")

Base = declarative_base()


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
        return args if not kwargs else args + sum(sorted(kwargs.items()), cls._kwmark)

    @classmethod
    def simple(cls, *args, **kwargs):
        """Return a cache key for the specified hashable arguments."""
        return cls(cls._to_tuple(*args, **kwargs))

    @classmethod
    def simple_noself(cls, *args, **kwargs):
        """Return a cache key for the specified hashable arguments, omitting the first positional argument."""
        return cls(cls._to_tuple(*args[1:], **kwargs))

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
    optional = "use_cached" if optional is True else optional
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
        key = CacheKey.simple_noself if isinstance(cache, DBCache) else CacheKey.simple

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
            description = "Use cached return values for previously used arguments if they exist"
            insert_kwonly_arg(wrapper, new_param, description, "bool", sig=sig)
        return wrapper
    return decorator


class FSCache:
    def __init__(self, cache_dir=None, cache_subdir=None, prefix=None, ext="txt", dumper=None, loader=None, binary=False):
        if cache_dir:
            self.cache_dir = os.path.join(cache_dir, cache_subdir) if cache_subdir else cache_dir
            validate_or_make_dir(self.cache_dir)
        else:
            self.cache_dir = get_user_cache_dir(cache_subdir)
        self.prefix = prefix or ""
        self._ext = ext
        self.dumper = dumper
        self.loader = loader
        self.binary = binary

    @property
    def ext(self):
        return ("." + self._ext) if self._ext else ""

    @property
    def read_mode(self):
        return "rb" if self.binary else "r"

    @property
    def write_mode(self):
        return "wb" if self.binary else "w"

    def filename_for_key(self, key):
        return "{}{}{}".format(self.prefix, key, self.ext)

    def path_for_key(self, key):
        return os.path.join(self.cache_dir, "{}{}{}".format(self.prefix, key, self.ext))

    @classmethod
    def _html_key_with_extras(cls, key, kwargs):
        for arg, name in (("params", "query"), ("data", "data"), ("json", "json")):
            value = kwargs.get(arg)
            if value:
                if hasattr(value, "items"):
                    value = sorted(value.items())
                key += "__{}__{}".format(name, urlencode(value, True))
        return key

    @classmethod
    def html_key(cls, self, endpoint, *args, **kwargs):
        key = "{}__{}".format(self.host, endpoint.replace("/", "_"))
        return cls._html_key_with_extras(key, kwargs)

    @classmethod
    def html_key_nohost(cls, self, endpoint, *args, **kwargs):
        key = endpoint.replace("/", "_")
        return cls._html_key_with_extras(key, kwargs)

    @classmethod
    def dated_html_key_func(cls, date_fmt="%Y-%m-%d", include_host=True):
        def key_func(self, endpoint, *args, **kwargs):
            if include_host:
                return "{}__{}__{}".format(self.host, now(date_fmt), url_quote(endpoint, ""))
            else:
                return "{}__{}".format(now(date_fmt), url_quote(endpoint, ""))
        return key_func

    @classmethod
    def dated_html_key(cls, self, endpoint, *args, **kwargs):
        return "{}__{}__{}".format(self.host, now("%Y-%m-%d"), url_quote(endpoint, ""))

    @classmethod
    def dated_html_key_nohost(cls, self, endpoint, *args, **kwargs):
        return "{}__{}".format(now("%Y-%m-%d"), url_quote(endpoint, ""))

    @synchronized
    def keys(self):
        p_len = len(self.prefix)
        e_len = len(self.ext)
        keys = [
            f[p_len:-e_len] for f in os.listdir(self.cache_dir) if f.startswith(self.prefix) and f.endswith(self.ext)
        ]
        return keys

    @synchronized
    def values(self):
        return [self[key] for key in self.keys()]

    @synchronized
    def items(self):
        return zip(self.keys(), self.values())

    def __getitem__(self, item):
        file_path = self.path_for_key(item)
        if not (os.path.exists(file_path) and os.path.isfile(file_path)):
            raise KeyError(item)

        kwargs = {} if self.binary else {"encoding": "utf-8"}
        with open(file_path, self.read_mode, **kwargs) as f:
            value = f.read()

        return self.loader(value) if self.loader else value

    def __setitem__(self, key, value):
        file_path = self.path_for_key(key)
        if self.dumper:
            value = self.dumper(value)

        kwargs = {} if self.binary else {"encoding": "utf-8"}
        with open(file_path, self.write_mode, **kwargs) as f:
            f.write(value)


class DBCacheEntry(Base):
    """A key, value pair for use in :class:`DBCache`"""
    __tablename__ = "cache"

    key = Column(PickleType, primary_key=True)
    value = Column(PickleType)

    def __repr__(self):
        return "<{}({!r})>".format(type(self).__name__, self.key)


class DBCache:
    """
    A dictionary-like cache that stores values in an SQLite3 DB.  Old cache files in the cache directory that begin with
    the same ``file_prefix`` and username that have non-matching dates in their filename will be deleted when a cache
    file with a new date is created.
    """

    def __init__(self, file_prefix, time_fmt="%Y-%m", db_dir="/var/tmp/ds_tools_cache/"):
        db_file_prefix = "{}.{}.".format(file_prefix, getuser())
        current_db = "{}{}.db".format(db_file_prefix, now(time_fmt))
        validate_or_make_dir(db_dir, permissions=0o1777)

        for fname in os.listdir(db_dir):
            if fname.startswith(db_file_prefix) and fname.endswith(".db") and fname != current_db:
                file_path = os.path.join(db_dir, fname)
                try:
                    if os.path.isfile(file_path):
                        log.debug("Deleting old cache file: {}".format(file_path))
                        os.remove(file_path)
                except OSError as e:
                    log.debug("Error deleting old cache file {}: [{}] {}".format(file_path, type(e).__name__, e))

        db_path = os.path.join(db_dir, current_db)

        self.engine = create_engine("sqlite:///{}".format(db_path), echo=False)
        self.meta = MetaData(self.engine)
        try:
            self.table = Table(DBCacheEntry.__tablename__, self.meta, autoload=True)
        except NoSuchTableError as e:
            Base.metadata.create_all(self.engine)
            self.table = Table(DBCacheEntry.__tablename__, self.meta, autoload=True)
        self.db_session = ScopedSession(self.engine)

    def keys(self):
        with self.db_session as session:
            for entry in session.query(DBCacheEntry):
                yield entry.key

    def values(self):
        with self.db_session as session:
            for entry in session.query(DBCacheEntry):
                yield entry.value

    def items(self):
        with self.db_session as session:
            for entry in session.query(DBCacheEntry):
                yield entry.key, entry.value

    def __getitem__(self, item):
        with synchronized(self):
            with self.db_session as session:
                try:
                    return session.query(DBCacheEntry).filter_by(key=item).one().value
                except (NoResultFound, OperationalError) as e:
                    raise KeyError(item) from e

    def __setitem__(self, key, value):
        with synchronized(self):
            with self.db_session as session:
                entry = DBCacheEntry(key=key, value=value)
                session.merge(entry)
                session.commit()


def disk_cached(prefix="/var/tmp/script_cache/", ext=None, date_fmt="%Y-%m-%d", compress=True):
    open_func = gzip.open if compress else open
    ext = ext or ("json.gz" if compress else "json")

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            if prefix.endswith("/"):
                cache_file_base = "{}{}_{}_".format(prefix, func.__name__, getuser())
            else:
                cache_file_base = "{}_{}_".format(prefix, getuser())
            cache_file = cache_file_base + "{}.{}".format(now(date_fmt), ext)
            cache_dir = os.path.dirname(cache_file)
            validate_or_make_dir(cache_dir, permissions=0o17777)

            existing_files = [os.path.join(cache_dir, file) for file in os.listdir(cache_dir)]
            with suppress(ValueError):
                existing_files.remove(cache_file)

            for file_path in fnmatch.filter(existing_files, cache_file_base + "*"):
                try:
                    if os.path.isfile(file_path):
                        log.debug("Deleting old cache file: {}".format(file_path))
                        os.remove(file_path)
                except OSError as e:
                    log.debug("Error deleting old cache file {}: [{}] {}".format(file_path, type(e).__name__, e))

            # Note: rb/wb and to_str/to_bytes are used below to handle reading/writing gzip files
            if os.path.exists(cache_file):
                with open_func(cache_file, "rb") as f:
                    return json.loads(to_str(f.read()))

            resp = func(*args, **kwargs)
            with open_func(cache_file, "wb") as f:
                f.write(to_bytes(json.dumps(resp, indent=4, sort_keys=True, cls=JSONSetEncoder)))
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
