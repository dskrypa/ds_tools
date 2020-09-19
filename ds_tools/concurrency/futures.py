"""
Utilities for working with Future objects from the stdlib concurrent.futures package.

:author: Doug Skrypa
"""

from collections import defaultdict
from concurrent.futures import Future
from itertools import count
from threading import Thread

__all__ = ['as_future']
_names = defaultdict(count)


def as_future(func, args=(), kwargs=None, daemon=None, cb=None):
    """
    Executes the given function in a separate thread.  Returns a :class:`Future<concurrent.futures.Future>` object
    immediately.

    :param func: The function to execute
    :param args: Positional arguments for the function
    :param kwargs: Keyword arguments for the function
    :param bool daemon: Whether the :class:`Thread<threading.Thread>` that the function runs in should be a daemon or
      not (default: see :attr:`daemon<threading.Thread.daemon>`)
    :param cb: A callback function that accepts one positional argument to be called when the future is complete.  The
      function will be called with the future object that completed.
    :return: A :class:`Future<concurrent.futures.Future>` object that will hold the results of executing the given
      function
    """
    future = Future()
    if cb is not None:
        future.add_done_callback(cb)
    func_name = func.__name__
    name = 'future:{}#{}'.format(func_name, next(_names[func_name]))
    thread = Thread(target=_run_func, args=(future, func, args, kwargs), name=name, daemon=daemon)
    thread.start()
    return future


def _run_func(future, func, args=(), kwargs=None):
    """
    Used by :class:`Future<concurrent.futures.Future>` as the :class:`Thread<threading.Thread>` target function, to wrap
    the execution of the given function and capture any exceptions / store its results.

    :param Future future: The :class:`Future<concurrent.futures.Future>` object in which the results of executing the
      given function should be stored
    :param func: The function to execute
    :param args: Positional arguments for the function
    :param kwargs: Keyword arguments for the function
    """
    kwargs = kwargs or {}
    if future.set_running_or_notify_cancel():   # True if state changes from PENDING to RUNNING, False if cancelled
        try:
            result = func(*args, **kwargs)
        except BaseException as e:
            future.set_exception(e)
        else:
            future.set_result(result)
