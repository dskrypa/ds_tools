#!/usr/bin/env python3

import logging
import os
import sys
import unittest
from concurrent import futures
from random import randint

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)
from ds_tools.logging import LogManager
from ds_tools.concurrency.ipc_process import InvalidRequest, IpcConnection, RequestType, WorkerProcess

log = logging.getLogger("ds_tools.{}".format(__name__))


class IpcTester(unittest.TestCase):
    def test_concurrent_requests(self):
        print()
        proc, ipc_conn = WorkerProcess.new_proc_and_conn()
        proc.start()
        proc.join(0.5)

        LogManager.create_default_logger(0, log_path=None)

        with futures.ThreadPoolExecutor(max_workers=8) as executor:
            _futures = {
                executor.submit(ipc_conn.request, *args): args for args in (
                    (RequestType.ECHO, 'test1'),
                    (RequestType.ECHO, 'test2'),
                    (RequestType.ECHO, 'test3'),
                    (RequestType.SUM, [1, 2, 3, 4, 5]),
                )
            }
            _futures.update({
                executor.submit(ipc_conn.request, *args): args for args in (
                    (RequestType.SUM, [randint(0, 10) for x in range(10)]) for y in range(10)
                )
            })
            for future in futures.as_completed(_futures):
                req_type, req_body = _futures[future]
                resp = future.result()
                if req_type == RequestType.ECHO:
                    self.assertEqual(req_body, resp)
                elif req_type == RequestType.SUM:
                    self.assertEqual(sum(req_body), resp)
                else:
                    self.fail('Unexpected req_type={!r} was submitted'.format(req_type))

        with self.assertRaises(InvalidRequest):
            ipc_conn.request(None)

        ipc_conn.request(RequestType.SHUTDOWN)
        proc.join(0.5)
        self.assertFalse(proc.is_alive())


if __name__ == "__main__":
    try:
        unittest.main(warnings='ignore', verbosity=2, exit=False)
    except KeyboardInterrupt:
        print()
