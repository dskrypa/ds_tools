"""
Futures that do not require a pool/executor.  Mostly modeled after the concurrent.futures package.

:author: Doug Skrypa
"""

import logging
from collections import defaultdict
from concurrent.futures import Future
from itertools import count
from threading import  Thread

__all__ = ['as_future']
log = logging.getLogger(__name__)
_names = defaultdict(count)


def as_future(func, args=(), kwargs=None):
    """
    Executes the given function in a separate thread.  Returns a :class:`Future` object immediately.

    :param func: The function to execute
    :param args: Positional arguments for the function
    :param kwargs: Keyword arguments for the function
    :return: A :class:`Future` object from :mod:`concurrent.futures` that will hold the results of executing the given
      function
    """
    future = Future()
    func_name = func.__name__
    name = 'future-{}-{}'.format(func_name, next(_names[func_name]))
    thread = Thread(target=_run_func, args=(future, func, args, kwargs), name=name)
    thread.start()
    return future


def _run_func(future, func, args=(), kwargs=None):
    """
    Used by :class:`Future` as the :class:`Thread` target function, to wrap the execution of the given function and
    capture any exceptions / store its results.

    :param Future future: The :class:`Future` object in which the results of executing the given function should be
      stored
    :param func: The function to execute
    :param args: Positional arguments for the function
    :param kwargs: Keyword arguments for the function
    """
    if future.set_running_or_notify_cancel():   # True if state changes from PENDING to RUNNING, False if cancelled
        try:
            result = func(*args, **kwargs)
        except BaseException as e:
            future.set_exception(e)
        else:
            future.set_result(result)
