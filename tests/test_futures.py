#!/usr/bin/env python3

import logging
import os
import socket
import sys
import unittest
from concurrent.futures import as_completed
from pathlib import Path
from threading import Thread

from flask import Flask, request

sys.path.append(Path(__file__).parents[1].as_posix())
from ds_tools.logging import LogManager
from ds_tools.http import RestClient

log = logging.getLogger(__name__)


def find_free_port():
    s = socket.socket()
    s.bind(('', 0))
    return s.getsockname()[1]


class FuturesTest(unittest.TestCase):
    def test_async_requests(self):
        print()
        response = 'Test app response'
        app = Flask(__name__)
        os.environ['FLASK_ENV'] = 'dev'

        @app.route('/')
        def root():
            return response

        @app.route('/shutdown')
        def shutdown_server():
            request.environ.get('werkzeug.server.shutdown')()

        port = find_free_port()
        app_thread = Thread(target=app.run, args=('localhost', port))
        app_thread.start()
        client = RestClient('localhost', port)

        futures = [client.async_get('/') for _ in range(5)]
        for future in as_completed(futures):
            resp = future.result()
            log.debug('Result: {}'.format(resp))
            self.assertEqual(resp.text, response)

        client.get('/shutdown', raise_non_200=False)
        app_thread.join()


if __name__ == '__main__':
    LogManager.create_default_logger(4, log_path=None)
    try:
        unittest.main(warnings='ignore', verbosity=2, exit=False)
    except KeyboardInterrupt:
        print()
