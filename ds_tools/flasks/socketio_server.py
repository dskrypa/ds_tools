"""
Utilities for running Flask servers with SocketIO

:author: Doug Skrypa
"""

import logging
from typing import Optional, Iterable
from uuid import uuid4

import requests
from flask import request, Response, Blueprint
from flask_socketio import SocketIO

from .server import FlaskServer

__all__ = ['SocketIOServer']
log = logging.getLogger(__name__)


class SocketIOServer(FlaskServer):
    def __init__(self, *args, blueprints: Optional[Iterable[Blueprint]] = None, **kwargs):
        self._socketio = None
        self.__shutdown_pw = str(uuid4())
        socketio_bp = Blueprint('socketio_base', __name__)
        socketio_bp.route('/shutdown', methods=['POST'])(self._shutdown_server)
        blueprints = list(blueprints) if blueprints else []
        blueprints.append(socketio_bp)
        super().__init__(*args, blueprints=blueprints, **kwargs)

    def start_server(self, async_mode='gevent'):
        log.info(f'Starting Flask app={self._app.name!r} on port={self._port}', extra={'color': 14})
        self._socketio = SocketIO(self._app, async_mode=async_mode)
        return self._socketio.run(self._app, host=self._host, port=self._port)

    def _shutdown_server(self):
        try:
            pw = request.get_json().get('password')
        except Exception:
            pw = None
        if request.remote_addr == '127.0.0.1' and pw == self.__shutdown_pw:
            log.info('Stopping REST server')
            self._socketio.stop()  # No return because the server will have stopped, so it cannot respond
        else:
            log.warning(f'Rejecting unauthorized stop request from {request.remote_addr}')
            return Response(status=403)

    def stop_server(self):
        try:
            resp = requests.post(
                f'http://localhost:{self._port}/shutdown', json={'password': self.__shutdown_pw}, timeout=0.1
            )
        except Exception:
            log.debug('Shutdown request timed out (expected)')
        else:
            log.debug(f'Unexpected shutdown response: {resp} - {resp.text}')
