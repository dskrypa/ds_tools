#!/usr/bin/env python

if __name__ == '__main__':
    from gevent import monkey
    monkey.patch_all()

import argparse
import logging
import platform
import socket
import sys
from pathlib import Path

from flask import Flask, jsonify

from ds_tools.flasks.server import init_logging

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.append(BASE_DIR.as_posix())

log = logging.getLogger(__name__)
app = Flask(__name__)
app.config.update(PROPAGATE_EXCEPTIONS=True, JSONIFY_PRETTYPRINT_REGULAR=True)


def main():
    parser = argparse.ArgumentParser('Example Flask Server')
    parser.add_argument('--use_hostname', '-u', action='store_true', help='Use hostname instead of localhost/127.0.0.1')
    parser.add_argument('--port', '-p', type=int, default=10000, help='Port to use')
    parser.add_argument('--verbose', '-v', action='count', help='Print more verbose log info (may be specified multiple times to increase verbosity)')
    parser.add_argument('--werkzeug', '-w', action='store_true', help='Use the werkzeug WSGI server instead of gunicorn/socketio')
    args = parser.parse_args()
    init_logging(None, args.verbose)

    if args.werkzeug:
        from ds_tools.flasks.server import FlaskServer as Server
    else:
        if platform.system() == 'Windows':
            from ds_tools.flasks.socketio_server import SocketIOServer as Server
        else:
            from ds_tools.flasks.gunicorn_server import GunicornServer as Server

    host = socket.gethostname() if args.use_hostname else None
    server = Server(app, args.port, host, debug=True)
    server.start_server()


@app.route('/')
def root():
    return jsonify({'hello': 'world'})


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print()
