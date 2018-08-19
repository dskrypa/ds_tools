#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
:author: Doug Skrypa
"""

import functools
import logging
import time
from collections import OrderedDict
from operator import attrgetter
from threading import Lock

from .itertools import partitioned

__all__ = ["cached_property", "classproperty", "partitioned_exec", "trace_entry", "timed", "rate_limited"]
log = logging.getLogger("ds_tools.decorate")


class cached_property:
    """
    A decorator that converts a method into a lazy property.  The wrapped method id called the first time to retrieve
    the result, and then that calculated result is used the next time the value is accessed.  Deleting the attribute
    from the instance resets the cached value and will cause it to be re-computed.
    """
    def __init__(self, func):
        self.__doc__ = func.__doc__
        self.func = func

    def __get__(self, obj, cls):
        if obj is None:
            return self
        value = obj.__dict__[self.func.__name__] = self.func(obj)
        return value


class cached_classproperty:
    def __init__(self, func):
        self.__doc__ = func.__doc__
        if not isinstance(func, (classmethod, staticmethod)):
            func = classmethod(func)
        self.func = func

    def __get__(self, obj, cls):
        try:
            return self.value
        except AttributeError:
            # noinspection PyCallingNonCallable
            value = self.value = self.func.__get__(obj, cls)()
            return value


class classproperty:
    """A read-only class property."""
    def __init__(self, func):
        self.__doc__ = func.__doc__
        if not isinstance(func, (classmethod, staticmethod)):
            func = classmethod(func)
        self.func = func

    def __get__(self, obj, cls):
        # noinspection PyCallingNonCallable
        return self.func.__get__(obj, cls)()


def partitioned_exec(n, container_factory, merge_fn=None, pos=0):
    """
    Decorator that partitions the sequence at args[pos] into groups of length n, and merges results of executing the
    decorated function/method for each partition of the sequence.

    Example usage:
    @partitioned_exec(4, dict, pos=1)
    def dict_example(self, seq):
        return {chr(97 + i): i for i in seq}

    @partitioned_exec(2, list, pos=2)
    def list_example(self, fn, seq):
        return [fn(i) for i in seq]

    :param int n: Maximum partition length
    :param container_factory: Callable similar to defaultdict's default_factory
    :param merge_fn: Function used to merge results
    :param pos: Position of the sequence to partition in args if an int is provided, or kwargs if a str is provided
    :return: Merged results from calling the decorated function/method for each generated partition of args[pos]
    """
    if isinstance(n, (attrgetter, str)):
        n = attrgetter(n) if isinstance(n, str) else n
    if merge_fn is None:
        if issubclass(container_factory, (dict, set)):
            merge_fn = lambda a, b: a.update(b)
        elif issubclass(container_factory, list):
            merge_fn = lambda a, b: a.extend(b)
        else:
            raise ValueError("partitioned_exec only provides merge_fn defaults for dict, set, and list types")

    def decorator(func):
        if isinstance(n, attrgetter):
            @functools.wraps(func)
            def wrapper(self, *args, **kwargs):
                psize = n(self)
                args = [self] + list(args)
                merged = container_factory()

                use_kw = isinstance(pos, str)
                for partition in partitioned(list(kwargs[pos] if use_kw else args[pos]), psize):
                    if use_kw:
                        kwargs[pos] = partition
                    else:
                        args[pos] = partition
                    merge_fn(merged, func(*args, **kwargs))
                return merged
        else:
            @functools.wraps(func)
            def wrapper(*args, **kwargs):
                args = list(args)
                merged = container_factory()
                use_kw = isinstance(pos, str)
                for partition in partitioned(list(kwargs[pos] if use_kw else args[pos]), n):
                    if use_kw:
                        kwargs[pos] = partition
                    else:
                        args[pos] = partition
                    merge_fn(merged, func(*args, **kwargs))
                return merged
        return wrapper
    return decorator


def trace_entry(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        arg_str = ", ".join("\"{}\"".format(v) if isinstance(v, str) else str(v) for v in args)
        kwarg_str = ", ".join("{}={}".format(k, "\"{}\"".format(v) if isinstance(v, str) else str(v)) for k, v in kwargs.items())
        print("{}({}, {})".format(func.__name__, arg_str, kwarg_str))
        return func(*args, **kwargs)
    return wrapper


def timed(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        start = time.time()
        r = func(*args, **kwargs)
        end = time.time()
        print("{} ran in {} s".format(func.__name__, end - start))
        return r
    return wrapper


def rate_limited(interval=0):
    """
    :param float interval: Interval between allowed invocations in seconds
    """
    if isinstance(interval, (attrgetter, str)):
        interval = attrgetter(interval) if isinstance(interval, str) else interval

    def decorator(func):
        last_call = 0
        lock = Lock()

        if isinstance(interval, attrgetter):
            @functools.wraps(func)
            def wrapper(self, *args, **kwargs):
                nonlocal last_call, lock
                obj_interval = interval(self)
                with lock:
                    elapsed = time.time() - last_call
                    if elapsed < obj_interval:
                        wait = obj_interval - elapsed
                        log.debug("Rate limited method '{}' is being delayed {:,.3f} seconds".format(func.__name__, wait))
                        time.sleep(wait)
                    last_call = time.time()
                    return func(*args, **kwargs)
        else:
            @functools.wraps(func)
            def wrapper(*args, **kwargs):
                nonlocal last_call, lock
                with lock:
                    elapsed = time.time() - last_call
                    if elapsed < interval:
                        wait = interval - elapsed
                        log.debug("Rate limited function '{}' is being delayed {:,.3f} seconds".format(func.__name__, wait))
                        time.sleep(wait)
                    last_call = time.time()
                    return func(*args, **kwargs)
        return wrapper
    return decorator


def retry_on_exception(retries=0, delay=0, *exception_classes, warn=True):
    """
    Decorator to wrap function with a callable that waits and retries when the given exceptions are encountered

    :param int retries: Number of times to retry; 0 (default) is equivalent to not using this wrapper
    :param float delay: Number of seconds to wait between an exception and a retry
    :param exception_classes: Exceptions to expect and gracefully retry upon catching
    :param bool warn: [KW-only] Log a warning when an exception is encountered
    :return: Decorator function that returns the wrapped/decorated function
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            nonlocal retries, delay, warn, exception_classes
            last_action = 0
            while retries >= 0:
                retries -= 1
                remaining = delay - (time.time() - last_action)
                if remaining > 0:
                    time.sleep(remaining)
                last_action = time.time()
                try:
                    return func(*args, **kwargs)
                except exception_classes as e:
                    if retries >= 0:
                        if warn:
                            fn_args = ", ".join(map(str, args)) if args else ""
                            if kwargs:
                                if fn_args:
                                    fn_args += ", "
                                fn_args += ", ".join("{}={}".format(k, v) for k, v in OrderedDict(kwargs).items())
                            fn_str = "{}({}".format(func.__name__, fn_args)
                            log.warning("Error calling {}: {}; retrying in {}s".format(fn_str, e, delay))
                    else:
                        raise e
        return wrapper
    return decorator
