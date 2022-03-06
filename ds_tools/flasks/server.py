"""
Utilities for running Flask servers

:author: Doug Skrypa
"""

import json
import logging
import os
import time
from itertools import chain
from uuid import uuid4
from typing import TYPE_CHECKING, Optional, Iterable

from flask import request, Blueprint, Response, session
from jinja2 import Template
from werkzeug.local import Local, release_local

if TYPE_CHECKING:
    from flask import Flask

from ..logging import ENTRY_FMT_DETAILED_UID, ENTRY_FMT_DETAILED_PID_UID
from ..logging import init_logging as _init_logging
from ..output.printer import PseudoJsonEncoder
from .patches import patch_http_exception
from .serialization import SerializableException

__all__ = ['FlaskServer', 'init_logging']
log = logging.getLogger(__name__)

_NotSet = object()
wz_local = Local()
base = Blueprint('base', __name__)
debug_bp = Blueprint('debug', __name__)


class FlaskServer:
    def __init__(
        self,
        app: 'Flask',
        port: int,
        host: Optional[str] = None,
        *,
        blueprints: Optional[Iterable[Blueprint]] = None,
        debug: bool = False,
    ):
        self._app = app
        self._port = port
        self._host = host or '0.0.0.0'
        self._debug = debug

        blueprints = list(blueprints) if blueprints else []
        blueprints.insert(0, base)
        if debug:
            blueprints.append(debug_bp)
            patch_http_exception()

        for bp in blueprints:
            log.debug(f'Registering blueprint={bp.name!r} pkg={bp.import_name!r} {bp.url_prefix=!r} {bp.subdomain=!r}')
            self._app.register_blueprint(bp)

        if debug:
            attrs = ('root_path', 'static_folder', 'template_folder')
            paths = {
                f'<{abp.__class__.__name__}: {abp.name}>': {attr: getattr(abp, attr) for attr in attrs}
                for abp in chain((app,), app.blueprints.values())
            }
            log.info(
                f'Initializing {self!r} with app'
                f'config={json.dumps(self._app.config, indent=4, sort_keys=True, cls=PseudoJsonEncoder)}\n'
                f'paths={json.dumps(paths, indent=4, cls=PseudoJsonEncoder)}'
            )

    def __repr__(self):
        return f'<{self.__class__.__name__}[{self._host}:{self._port}, app={self._app}]>'

    def start_server(self, **options):
        import socket
        from flask.cli import show_server_banner
        from werkzeug.serving import make_server

        app = self._app
        app.debug = bool(self._debug)
        show_server_banner(app.env, app.debug, app.name, False)
        log.warning(
            'Using werkzeug.serving.make_server instead of Flask.run, so behavior may be slightly different'
            ' - use a production WSGI server instead of the built-in development server!',
            extra={'color': 11},
        )

        options.setdefault('threaded', True)
        self._server = srv = make_server(self._host, self._port, app, **options)  # noqa

        try:
            unix_socket = srv.socket.family == socket.AF_UNIX
        except AttributeError:
            unix_socket = False
        host = self._host if self._host not in ('', '*') else 'localhost'
        if unix_socket:
            log.info(f' * Running on {host} (Press CTRL+C to quit)')
        else:
            if ':' in host:
                host = f'[{host}]'
            scheme = 'http' if options.get('ssl_context') is None else 'https'
            log.info(f' * Running on {scheme}://{host}:{srv.socket.getsockname()[1]}/ (Press CTRL+C to quit)')

        srv.serve_forever()

    def stop_server(self):
        self._server.shutdown()


def _patch_log_record():
    """
    Adds a ``uid`` attribute to all :class:`LogRecord` objects by patching :meth:`LogRecord.__init__`.  It does not work
    as a property or cached_property because of the way that LogRecord objects are formatted - the formatter calls
    ``return self._fmt % record.__dict__`` without first attempting to access the value as a property, so it doesn't
    have a chance to be stored lazily.
    """
    original_init = logging.LogRecord.__init__  # noqa

    def init(self, *args, **kwargs):
        self.uid = getattr(wz_local, 'uid', '-')
        original_init(self, *args, **kwargs)

    logging.LogRecord.__init__ = init


def init_logging(
    log_path: Optional[str],
    verbose: int = 0,
    pid: bool = False,
    log_fmt: Optional[str] = None,
    patch_log_record: bool = True,
    **kwargs
):
    """
    :param str log_path: Location to store log file
    :param bool verbose: Verbosity
    :param bool pid: Include pid in the default log format, if no specific format is specified
    :param str log_fmt: The log format to use
    :param bool patch_log_record: Patch :class:`LogRecord` to include a ``uid`` attribute for tracking actions related
      to specific requests (see :func:`_patch_log_record`)
    :param kwargs: Additional kwargs to pass to :func:`init_logging<ds_tools.logging.init_logging>`
    :return: See :func:`init_logging<ds_tools.logging.init_logging>`
    """
    log_fmt = log_fmt or (ENTRY_FMT_DETAILED_PID_UID if pid else ENTRY_FMT_DETAILED_UID)
    init_args = {
        'names': None,
        'date_fmt': '%Y-%m-%d %H:%M:%S.%f %Z',
        'streams': verbose,
        'log_path': log_path,
        'file_fmt': log_fmt,
        'entry_fmt': log_fmt,
    }
    init_args.update(kwargs)
    if patch_log_record:
        _patch_log_record()
    return _init_logging(verbose, **init_args)


@base.app_errorhandler(SerializableException)
def handle_response_exception(exc):
    return exc.as_response()


@base.before_app_request
def before_requests():
    env = request.environ
    wz_local.time = time.monotonic()
    wz_local.uid = str(uuid4())
    user = request.remote_user or '-'
    method = request.method
    path = request.path
    qs = env.get('QUERY_STRING')
    ip = request.remote_addr
    referrer = request.referrer
    scheme = 'ws' if 'wsgi.websocket' in env else 'http'
    log.info(f'Beginning request for {ip=} {user=} {scheme=} {method=} {path=} {qs=!r} {referrer=!r}')


@base.after_app_request
def after_requests(response: Response):
    duration = time.monotonic() - wz_local.time
    user = request.remote_user or '-'
    method = request.method
    path = request.path
    code = response.status_code
    size = response.content_length
    if 'wsgi.websocket' in request.environ:
        log.info(f'Finished websocket request {duration=:.3f} s for {user=} {path=}')
    else:
        log.info(f'Returning {code=} {duration=:.3f} s {size=} for {user=} {method=} {path=}')

    release_local(wz_local)
    return response


@debug_bp.route('/debug')
def debug_info():
    debug_table_template = """
    {% for tbl_name, tbl in tables.items() %}
        <h1>{{tbl_name}}</h1>
        <table>
            {% for key, val in tbl.items() %}
                <tr><td>{{key}}</td><td>{{val}}</td></tr>
            {% endfor %}
        </table>
    {% endfor %}
    """
    skip = {'environ', 'args', 'headers', '_MutableMapping__marker'}
    tables = {
        'session': {
            k: getattr(session, k)
            for k in sorted(dir(session))
            if k not in skip and hasattr(session, k) and not k.startswith('__')
        },
        'request': {
            k: getattr(request, k)
            for k in sorted(dir(request))
            if k not in skip and hasattr(request, k) and not k.startswith('__')
        },
        'request.environ': {k: request.environ[k] for k in sorted(request.environ)},
        'os.environ': {k: os.environ[k] for k in sorted(os.environ)},
        'request.args': {k: request.args[k] for k in sorted(request.args)},
        'request.headers': {k: request.headers[k] for k in sorted(request.headers.keys())},
    }
    return Response(Template(debug_table_template).render(tables=tables))
