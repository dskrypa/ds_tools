"""
Example implementation of a Process that can communicate with other processes via a Pipe.  Handles multiple types of
simple requests.

:author: Doug Skrypa
"""

import logging
import os
import time
from enum import Enum
from multiprocessing import Process, Pipe, Event, Lock
from threading import Thread

from ..logging import init_logging

__all__ = ['InvalidRequest', 'IpcConnection', 'RequestType', 'WorkerProcess']
log = logging.getLogger(__name__)


class RequestType(Enum):
    ECHO = 1
    SUM = 2
    SHUTDOWN = 3


class InvalidRequest(Exception):
    pass


class WorkerProcess:
    def __init__(self, req_event, conn):
        self.req_event = req_event
        self.conn = conn
        self.can_run = True

    @classmethod
    def new_proc_and_conn(cls, verbose=0):
        """
        Create a new Process with :meth:`WorkerProcess.init_and_run` as the target, and a new :class:`IpcConnection` for
        other processes to be able to communicate with it.  The :class:`IpcConnection` handles locking so that the
        target process only receives one request at a time.

        :return tuple: Tuple of (Process, IpcConnection)
        """
        req_lock = Lock()
        req_event = Event()
        proc_conn, conn = Pipe()
        proc = Process(target=WorkerProcess.init_and_run, args=(req_event, proc_conn), kwargs={'verbose': verbose})
        ipc_conn = IpcConnection(req_lock, req_event, conn)
        return proc, ipc_conn

    @classmethod
    def init_and_run(cls, *args, verbose=0, **kwargs):
        init_logging(verbose, log_path=None)
        instance = cls(*args, ** kwargs)
        instance.start_threads()

    def request_processor(self):
        log.info('request_processor: started')
        while True:
            self.req_event.wait()
            if not self.can_run:
                log.debug('request_processor: exiting')
                break
            req_type, request = self.conn.recv()
            self.req_event.clear()
            log.debug('request_processor: Received request: {}'.format(req_type))
            if req_type == RequestType.ECHO:
                self.conn.send(request)
            elif req_type == RequestType.SUM:
                self.conn.send(sum(request))
            elif req_type == RequestType.SHUTDOWN:
                self.can_run = False
                log.info('request_processor: Received SHUTDOWN command - exiting')
                return
            else:
                self.conn.send(InvalidRequest(req_type))

    def worker(self):
        log.info('worker running')
        i = 0
        while self.can_run:
            i += 1
            time.sleep(0.25)

        log.info('Worker finished after {} loops'.format(i))

    def start_threads(self):
        log.info('{} started with pid={}'.format(self, os.getpid()))
        threads = [
            Thread(target=self.request_processor, daemon=True),
            Thread(target=self.worker, daemon=True)
        ]
        for t in threads:
            t.start()

        log.debug('{}: worker threads started'.format(self))
        for t in threads:
            t.join()


class IpcConnection:
    def __init__(self, req_lock, req_event, conn):
        self.req_lock = req_lock
        self.req_event = req_event
        self.conn = conn

    def request(self, req_type, body=None):
        with self.req_lock:
            self.req_event.set()
            log.debug('Sending request: {}'.format(req_type))
            self.conn.send((req_type, body))
            if req_type != RequestType.SHUTDOWN:
                resp = self.conn.recv()
            else:
                resp = None

        if isinstance(resp, BaseException):
            raise resp
        return resp
