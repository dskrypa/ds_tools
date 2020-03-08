"""
:author: Doug Skrypa
"""

import functools
import logging
import platform
import sys
import time
import traceback
from collections import OrderedDict
from functools import wraps
from operator import attrgetter
from threading import Lock

from .itertools import partitioned

__all__ = [
    'cached_property_or_err', 'classproperty', 'partitioned_exec', 'rate_limited', 'timed', 'trace_entry',
    'trace_entry_and_dump_stack', 'wrap_main', 'primed_coroutine', 'basic_coroutine'
]
log = logging.getLogger(__name__)

ON_WINDOWS = platform.system().lower() == 'windows'


def wrap_main(main):
    """
    Handle quirks related to the inability to use ``signal.signal(signal.SIGPIPE, signal.SIG_DFL)`` in Windows, and
    standardize the handling of KeyboardInterrupt and logging of stack traces/errors on exit with ``sys.exit(1)``.

    :param main: The main function of a program
    :return: The main function, wrapped with exception handlers for common things that need to be handled at exit
    """
    @wraps(main)
    def run_main(*args, **kwargs):
        try:
            try:
                main(*args, **kwargs)
            except OSError as e:
                if ON_WINDOWS and e.errno == 22:
                    # When using |head, the pipe will be closed when head is done, but Python will still think that it
                    # is open - checking whether sys.stdout is writable or closed doesn't work, so triggering the
                    # error again seems to be the most reliable way to detect this (hopefully) without false positives
                    try:
                        sys.stdout.write('\n')
                        sys.stdout.flush()
                    except OSError:
                        pass
                    else:
                        raise   # If it wasn't the expected error, let the main Exception handler below handle it
                else:
                    raise
        except KeyboardInterrupt:
            print()
        except BrokenPipeError:
            pass
        except Exception as e:
            if _logger_has_non_null_handlers(log):
                log.log(19, traceback.format_exc())     # hide tb since exc may be expected unless output is --verbose
                log.error(e)
            else:               # If logging wasn't configured, or the error occurred before logging could be configured
                print(traceback.format_exc(), file=sys.stderr)
            sys.exit(1)
        finally:
            """
            Prevent the following when piping output to utilities such as ``| head``:
                Exception ignored in: <_io.TextIOWrapper name='<stdout>' mode='w' encoding='utf-8'>
                OSError: [Errno 22] Invalid argument
            """
            try:
                sys.stdout.close()
            except Exception:
                pass
    return run_main


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
            raise ValueError('partitioned_exec only provides merge_fn defaults for dict, set, and list types')

    def decorator(func):
        if isinstance(n, attrgetter):
            @functools.wraps(func)
            def wrapper(*args, **kwargs):
                args = list(args)           # necessary to replace the value at a given index
                self = args[0]
                psize = n(self)
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
        arg_str = ', '.join('{!r}'.format(v) if isinstance(v, str) else str(v) for v in args)
        kwarg_str = ', '.join('{}={}'.format(k, '{!r}'.format(v) if isinstance(v, str) else str(v)) for k, v in kwargs.items())
        print('{}({}, {})'.format(func.__name__, arg_str, kwarg_str))
        return func(*args, **kwargs)
    return wrapper


def trace_entry_and_dump_stack(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        arg_str = ', '.join('{!r}'.format(v) if isinstance(v, str) else str(v) for v in args)
        kwarg_str = ', '.join('{}={}'.format(k, '{!r}'.format(v) if isinstance(v, str) else str(v)) for k, v in kwargs.items())
        print('{}({}, {})\n{}'.format(func.__name__, arg_str, kwarg_str, ''.join(traceback.format_stack())))
        val = func(*args, **kwargs)
        print('finished {}({}, {})'.format(func.__name__, arg_str, kwarg_str))
        return val
    return wrapper


def timed(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        start = time.time()
        r = func(*args, **kwargs)
        end = time.time()
        print('{} ran in {} s'.format(func.__name__, end - start))
        return r
    return wrapper


def rate_limited(interval=0, log_lvl=logging.DEBUG):
    """
    :param float interval: Interval between allowed invocations in seconds
    :param int log_lvl: The log level that should be used to indicate that the wrapped function is being delayed
    """
    is_attrgetter = isinstance(interval, (attrgetter, str))
    if is_attrgetter:
        interval = attrgetter(interval) if isinstance(interval, str) else interval

    def decorator(func):
        last_call = 0
        lock = Lock()
        log_fmt = 'Rate limited {} {!r} is being delayed {{:,.3f}} seconds'.format(
            'method' if is_attrgetter else 'function', func.__name__
        )
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            nonlocal last_call, lock
            obj_interval = interval(args[0]) if is_attrgetter else interval
            with lock:
                elapsed = time.monotonic() - last_call
                if elapsed < obj_interval:
                    wait = obj_interval - elapsed
                    log.log(log_lvl, log_fmt.format(wait))
                    time.sleep(wait)
                last_call = time.monotonic()
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
                            fn_args = ', '.join(map(str, args)) if args else ''
                            if kwargs:
                                if fn_args:
                                    fn_args += ', '
                                fn_args += ', '.join('{}={}'.format(k, v) for k, v in OrderedDict(kwargs).items())
                            fn_str = '{}({}'.format(func.__name__, fn_args)
                            log.warning('Error calling {}: {}; retrying in {}s'.format(fn_str, e, delay))
                    else:
                        raise e
        return wrapper
    return decorator


def _logger_has_non_null_handlers(logger):
    # Based on logging.Logger.hasHandlers(), but checks that they are not all NullHandlers
    # Copied from ds_tools.logging to prevent circular dependency
    c = logger
    rv = False
    while c:
        if c.handlers and not all(isinstance(h, logging.NullHandler) for h in c.handlers):
            rv = True
            break
        if not c.propagate:
            break
        else:
            c = c.parent
    return rv
