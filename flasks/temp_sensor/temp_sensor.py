#!/usr/bin/env python3
"""
Flask server for providing temperature and humidity info

:author: Doug Skrypa
"""

import argparse
import logging
import signal
import socket
import sys
import traceback
import uuid
from pathlib import Path

import adafruit_dht as dht
import eventlet
from flask import Flask, request, Response, jsonify
from flask_socketio import SocketIO
from requests import Session
from werkzeug.http import HTTP_STATUS_CODES as codes

flask_dir = Path(__file__).resolve().parent
sys.path.append(flask_dir.parents[1].as_posix())
from ds_tools.logging import LogManager

log = logging.getLogger('ds_tools.temp_sensor.server')

socketio = None
shutdown_pw = None
stopped = False
server_port = None
app = Flask(__name__)
app.config.update(PROPAGATE_EXCEPTIONS=True, JSONIFY_PRETTYPRINT_REGULAR=True)


@app.route('/shutdown', methods=['POST'])
def shutdown_server():
    user_ip = request.environ.get('REMOTE_ADDR')
    data = request.get_json()
    if data.get('password') == shutdown_pw:
        log.info('Stopping server...')
        socketio.stop()
    else:
        log.info('Rejecting unauthorized stop request from {}'.format(user_ip))
        return Response(status=403)


@app.route('/read')
def read_sensors():
    humidity, temp = dht.read_retry(dht.DHT22, 4)
    return jsonify({'humidity': humidity, 'temperature': temp})


class ResponseException(Exception):
    def __init__(self, code, reason):
        super().__init__()
        self.code = code
        self.reason = reason
        if isinstance(reason, Exception):
            log.error(traceback.format_exc())
        log.error(self.reason)

    def __repr__(self):
        return '<{}({}, {!r})>'.format(type(self).__name__, self.code, self.reason)

    def __str__(self):
        return '{}: [{}] {}'.format(type(self).__name__, self.code, self.reason)

    def as_response(self):
        resp = jsonify({'error_code': codes[self.code], 'error': self.reason})
        resp.status_code = self.code
        return resp


@app.errorhandler(ResponseException)
def handle_response_exception(err):
    return err.as_response()


def start_server(run_args):
    log.info('Starting Flask server on port={}'.format(run_args['port']))
    global socketio, shutdown_pw, server_port
    server_port = run_args['port']
    shutdown_pw = str(uuid.uuid4())
    socketio = SocketIO(app, async_mode='eventlet')
    socketio.run(app, **run_args)


def stop_server():
    with Session() as session:
        log.info('Telling local server to shutdown...')
        try:
            resp = session.post(
                'http://localhost:{}/shutdown'.format(server_port), json={'password': shutdown_pw}, timeout=1
            )
        except Exception as e:
            log.debug('Shutdown request timed out (this is expected)')
        else:
            log.debug('Shutdown response: {} - {}'.format(resp, resp.text))


def stop_everything():
    global stopped
    if not stopped:
        stop_server()
        stopped = True


def handle_signals(sig_num=None, frame=None):
    log.info('Caught signal {} - shutting down'.format(sig_num))
    stop_everything()
    sys.exit(0)


if __name__ == '__main__':
    parser = argparse.ArgumentParser('Temp Sensor Flask Server')
    parser.add_argument('--use_hostname', '-u', action='store_true', help='Use hostname instead of localhost/127.0.0.1')
    parser.add_argument('--port', '-p', type=int, help='Port to use', required=True)
    parser.add_argument('--verbose', '-v', action='count', help='Print more verbose log info (may be specified multiple times to increase verbosity)')
    args = parser.parse_args()
    lm = LogManager.create_default_logger(args.verbose, log_path=None)

    flask_logger = logging.getLogger('flask.app')
    for handler in lm.logger.handlers:
        if handler.name == 'stderr':
            flask_logger.addHandler(handler)

    run_args = {'port': args.port}
    if args.use_hostname:
        run_args['host'] = socket.gethostname()

    signal.signal(signal.SIGTERM, handle_signals)
    signal.signal(signal.SIGINT, handle_signals)

    try:
        start_server(run_args)
        # app.run(**run_args)
    except Exception as e:
        log.debug(traceback.format_exc())
        log.error(e)
