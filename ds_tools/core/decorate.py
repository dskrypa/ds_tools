"""
:author: Doug Skrypa
"""

from __future__ import annotations

import logging
from functools import wraps, update_wrapper, partial
from operator import attrgetter
from threading import Lock
from time import sleep, monotonic
from traceback import format_stack
from typing import Callable, Union, Type, ParamSpec, TypeVar, Generic

from .itertools import partitioned

__all__ = [
    'cached_property_or_err', 'classproperty', 'partitioned_exec', 'rate_limited', 'timed', 'trace_entry', 'trace_exit',
    'trace_entry_and_dump_stack', 'primed_coroutine', 'basic_coroutine', 'trace_entry_and_exit'
]
log = logging.getLogger(__name__)

P = ParamSpec('P')
T = TypeVar('T')


class cached_property_or_err:
    def __init__(self, func):
        self.__doc__ = func.__doc__
        self.func = func
        self.had_err = None
        self.result = None

    def __get__(self, obj, cls):
        if obj is None:
            return self
        elif self.had_err is None:
            try:
                self.result = self.func(obj)
            except Exception as e:
                self.result = e
                self.had_err = True
            else:
                self.had_err = False

        if self.had_err:
            raise self.result
        return self.result


class cached_classproperty(classmethod):
    def __init__(self, func: Callable):
        super().__init__(property(func))  # noqa  # makes Sphinx handle it better than if this was not done
        self.__doc__ = func.__doc__
        self.func = func
        self.values = {}

    def __get__(self, obj: None, cls):  # noqa
        try:
            return self.values[cls]
        except KeyError:
            self.values[cls] = value = self.func(cls)
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


# region Coroutines


def primed_coroutine(func):
    """Primes the wrapped coroutine so users do not need to manually send None or call next() on it."""
    @wraps(func)
    def _primed_coroutine(*args, **kwargs):
        gen = func(*args, **kwargs)
        next(gen)
        return gen
    return _primed_coroutine


def basic_coroutine(func):
    """Wraps a coroutine so the user does not need to prime it or handle a StopIteration on the last send"""
    @primed_coroutine
    @wraps(func)
    def _basic_coroutine(*args, **kwargs):
        while True:
            result = yield from func(*args, **kwargs)
    return _basic_coroutine


# endregion


def partitioned_exec(n: Union[int, str, attrgetter], container_factory, merge_fn=None, pos: Union[int, str] = 0):
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

    :param n: Maximum partition length
    :param container_factory: Callable similar to defaultdict's default_factory
    :param merge_fn: Function used to merge results
    :param pos: Position of the sequence to partition in args if an int is provided, or kwargs if a str is provided
    :return: Merged results from calling the decorated function/method for each generated partition of args[pos]
    """
    if isinstance(n, (attrgetter, str)):
        n = attrgetter(n) if isinstance(n, str) else n
    if merge_fn is None:
        if issubclass(container_factory, (dict, set)):
            merge_fn = lambda a, b: a.update(b)  # noqa
        elif issubclass(container_factory, list):
            merge_fn = lambda a, b: a.extend(b)  # noqa
        else:
            raise ValueError('partitioned_exec only provides merge_fn defaults for dict, set, and list types')

    use_kw = isinstance(pos, str)

    def decorator(func):
        if isinstance(n, attrgetter):
            @wraps(func)
            def wrapper(*args, **kwargs):
                args = list(args)           # necessary to replace the value at a given index
                self = args[0]
                psize: int = n(self)  # noqa
                merged = container_factory()
                for partition in partitioned(kwargs[pos] if use_kw else args[pos], psize):
                    if use_kw:
                        kwargs[pos] = partition
                    else:
                        args[pos] = partition
                    merge_fn(merged, func(*args, **kwargs))
                return merged
        else:
            @wraps(func)
            def wrapper(*args, **kwargs):
                args = list(args)
                merged = container_factory()
                for partition in partitioned(kwargs[pos] if use_kw else args[pos], n):
                    if use_kw:
                        kwargs[pos] = partition
                    else:
                        args[pos] = partition
                    merge_fn(merged, func(*args, **kwargs))
                return merged
        return wrapper
    return decorator


# region Tracing


def trace_entry(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        arg_str = ', '.join(_repr_or_str(v) for v in args)
        kwarg_str = ', '.join(f'{k}={_repr_or_str(v)}' for k, v in kwargs.items())
        print(f'{func.__name__}({arg_str}, {kwarg_str})')
        return func(*args, **kwargs)
    return wrapper


def trace_entry_and_exit(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        arg_str = ', '.join(_repr_or_str(v) for v in args)
        kwarg_str = ', '.join(f'{k}={_repr_or_str(v)}' for k, v in kwargs.items())
        print(f'{func.__name__}({arg_str}, {kwarg_str})')
        val = func(*args, **kwargs)
        print(f'finished {func.__name__}({arg_str}, {kwarg_str})')
        return val
    return wrapper


def trace_exit(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        arg_str = ', '.join(_repr_or_str(v) for v in args)
        kwarg_str = ', '.join(f'{k}={_repr_or_str(v)}' for k, v in kwargs.items())
        val = func(*args, **kwargs)
        print(f'{func.__name__}(\n    {arg_str}, {kwarg_str}\n) => {val!r}')
        return val
    return wrapper


def trace_entry_and_dump_stack(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        arg_str = ', '.join(_repr_or_str(v) for v in args)
        kwarg_str = ', '.join(f'{k}={_repr_or_str(v)}' for k, v in kwargs.items())
        print(f'{func.__name__}({arg_str}, {kwarg_str})\n' + ''.join(format_stack()))
        val = func(*args, **kwargs)
        print(f'finished {func.__name__}({arg_str}, {kwarg_str})')
        return val
    return wrapper


def _repr_or_str(value) -> str:
    return repr(value) if isinstance(value, str) else str(value)

# endregion


def timed(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        start = monotonic()
        r = func(*args, **kwargs)
        end = monotonic()
        print(f'{func.__name__} ran in {end - start} s')
        return r
    return wrapper


def rate_limited(interval: Union[float, str, attrgetter] = 0, log_lvl: int = logging.DEBUG):
    """
    :param interval: Interval between allowed invocations in seconds
    :param log_lvl: The log level that should be used to indicate that the wrapped function is being delayed
    """
    is_attrgetter = isinstance(interval, (attrgetter, str))
    if is_attrgetter:
        interval = attrgetter(interval) if isinstance(interval, str) else interval

    fn_type = 'method' if is_attrgetter else 'function'

    def decorator(func):
        last_call = 0
        lock = Lock()

        @wraps(func)
        def wrapper(*args, **kwargs):
            nonlocal last_call
            obj_interval = interval(args[0]) if is_attrgetter else interval
            with lock:
                elapsed = monotonic() - last_call
                if elapsed < obj_interval:
                    wait = obj_interval - elapsed
                    log.log(log_lvl, f'Rate limited {fn_type} {func.__name__!r} is being delayed {wait:,.3f} seconds')
                    sleep(wait)
                last_call = monotonic()
                return func(*args, **kwargs)
        return wrapper
    return decorator


def retry_on_exception(retries: int = 0, delay: float = 0, *exception_classes: Type[Exception], warn: bool = True):
    """
    Decorator to wrap function with a callable that waits and retries when the given exceptions are encountered

    :param retries: Number of times to retry; 0 (default) is equivalent to not using this wrapper
    :param delay: Number of seconds to wait between an exception and a retry
    :param exception_classes: Exceptions to expect and gracefully retry upon catching
    :param warn: [KW-only] Log a warning when an exception is encountered
    :return: Decorator function that returns the wrapped/decorated function
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            remaining = retries
            last_action = 0
            while remaining >= 0:
                remaining -= 1
                if (sleep_time := delay - (monotonic() - last_action)) > 0:
                    sleep(sleep_time)
                last_action = monotonic()
                try:
                    return func(*args, **kwargs)
                except exception_classes as e:
                    if remaining >= 0:
                        if warn:
                            groups = (map(repr, args), (f'{k}={v!r}' for k, v in kwargs.items()))
                            fn_args = ', '.join(arg for group in groups for arg in group)
                            log.warning(f'Error calling {func.__name__}({fn_args}): {e}; retrying in {delay}s')
                    else:
                        raise
        return wrapper
    return decorator


class flex_method(Generic[P, T]):
    """
    A decorator for a method that can be used as either a classmethod or a normal method.

    An explicit alternate handler can be registered to be used when called as a class/normal method.  By default, the
    same method is used for both.
    """

    def __init__(self, func: Callable[P, T]):
        self.inst_func = self.cls_func = func
        update_wrapper(self, func)

    def __get__(self, instance, cls) -> Callable[P, T]:
        if instance is None:
            return partial(self.cls_func, cls)
        else:
            return partial(self.inst_func, instance)

    def classmethod(self, func: Callable[P, T]) -> flex_method[P, T]:
        self.cls_func = func
        return self

    def method(self, func: Callable[P, T]) -> flex_method[P, T]:
        self.inst_func = func
        return self
