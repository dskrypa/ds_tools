"""
:author: Doug Skrypa
"""

import atexit
import logging
import multiprocessing
import threading
from concurrent.futures import Future, ThreadPoolExecutor
# from concurrent.futures.thread import _WorkItem
from itertools import count
from queue import Empty as QueueEmpty
from traceback import format_exception

__all__ = ['Ipc', 'IpcStateError', 'IpcError']
log = logging.getLogger(__name__)


class RemoteTraceback(Exception):
    def __init__(self, tb):
        self.tb = tb

    def __str__(self):
        return self.tb


class ExceptionWithTraceback:
    def __init__(self, exc, tb):
        self.exc = exc
        self.tb = '\n"""\n{}"""'.format(''.join(format_exception(type(exc), exc, tb)))

    def __reduce__(self):
        return _rebuild_exc, (self.exc, self.tb)


def _rebuild_exc(exc, tb):
    exc.__cause__ = RemoteTraceback(tb)
    return exc


class IpcError(Exception):
    """Base IPC exception"""


class IpcStateError(IpcError):
    """IPC state does not allow the attempted action"""


class Ipc:
    def __init__(self, send_q, recv_q, req_handlers=4):
        """
        :param Queue send_q: The :class:`Queue<multiprocessing.Queue>` through which to send data
        :param Queue recv_q: The :class:`Queue<multiprocessing.Queue>` through which to receive data
        """
        self._send_q = send_q
        self._recv_q = recv_q
        self._lock = threading.RLock()
        self._counter = count()
        self._pending = {}
        self._req_handlers = req_handlers
        self._pool = None
        self.shutdown = threading.Event()

    @classmethod
    def init_pair(cls, req_handlers=4):
        queue_1 = multiprocessing.Queue()
        queue_2 = multiprocessing.Queue()
        return cls(queue_1, queue_2, req_handlers), cls(queue_2, queue_1, req_handlers)

    def request(self, func, args=(), kwargs=None):
        if self.shutdown.is_set():
            raise IpcStateError('Unable to initiate new request - shutting down')

        with self._lock:
            req_id = next(self._counter)
            future = self._pending[req_id] = Future()

            if self.shutdown.is_set():      # last chance before sending it
                self._cancel(req_id)
                raise IpcStateError('Unable to initiate new request - shutting down')

            self._send_q.put((req_id, func, args, kwargs))
        try:
            future.set_running_or_notify_cancel()
        except RuntimeError as e:
            raise IpcStateError('Request was cancelled after sending it') from e
        return future

    def request_sync(self, *args, **kwargs):
        future = self.request(*args, **kwargs)
        return future.result()

    def _cancel(self, req_id):
        with self._lock:
            future = self._pending.pop(req_id)
            if future.cancel():
                try:
                    future.set_running_or_notify_cancel()
                except RuntimeError:
                    pass

    def reply(self, req_id, result=None, exc=None):
        try:
            self._send_q.put((req_id, result, exc))
        except BaseException as e:
            exc = ExceptionWithTraceback(e, e.__traceback__)
            self._send_q.put((req_id, result, exc))

    def _wrap_call(self, req_id, func, args, kwargs):
        kwargs = kwargs or {}
        try:
            result = func(*args, **kwargs)
        except BaseException as e:
            self.reply(req_id, exc=e)
        else:
            self.reply(req_id, result=result)

    def run(self):
        self._pool = ThreadPoolExecutor(max_workers=self._req_handlers)
        atexit.register(self.shutdown.set)
        shutdown = self.shutdown
        q = multiprocessing.Queue()
        while not shutdown.is_set():
            try:
                msg = self._recv_q.get(timeout=0.05)
            except QueueEmpty:
                pass
            else:
                if len(msg) == 3:
                    req_id, result, exc = msg
                    try:
                        with self._lock:
                            future = self._pending.pop(req_id)
                    except KeyError:
                        log.warning('Received result for unexpected req_id={}'.format(req_id))
                    else:
                        if exc:
                            future.set_exception(exc)
                        else:
                            future.set_result(result)
                elif len(msg) == 4:
                    req_id, func, args, kwargs = msg
                    name_parts = func.split('.')
                    first = name_parts.pop(0)
                    try:
                        obj = locals()[first]
                    except KeyError:
                        self.reply(req_id, exc=NameError('Unable to call {} - {!r} does not exist'.format(func, first)))
                    else:
                        while name_parts:
                            part = name_parts.pop(0)
                            try:
                                obj = getattr(obj, part)
                            except AttributeError as e:
                                self.reply(req_id, exc=e)
                                break
                        self._pool.submit(self._wrap_call, req_id, obj, args, kwargs)
                else:
                    log.warning('Received unexpected message: {!r}'.format(msg))

        with self._lock:
            try:
                self._send_q.close()
            except Exception:
                pass
            for req_id in list(self._pending):
                self._cancel(req_id)
