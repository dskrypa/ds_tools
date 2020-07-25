"""
Utilities for running Flask servers

:author: Doug Skrypa
"""

import logging
import os
import time
from uuid import uuid4
from typing import TYPE_CHECKING, Optional, Iterable

from flask import request, Blueprint, Response, session
from jinja2 import Template
from werkzeug.local import Local, release_local

if TYPE_CHECKING:
    from flask import Flask

from ..logging import add_context_filter, ENTRY_FMT_DETAILED_UID, ENTRY_FMT_DETAILED_PID_UID
from ..logging import init_logging as _init_logging
from .serialization import SerializableException

__all__ = ['FlaskServer', 'init_logging', 'UniqueIdFilter']
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

        blueprints = list(blueprints) if blueprints else []
        blueprints.insert(0, base)
        if debug:
            blueprints.append(debug_bp)
        for bp in blueprints:
            log.debug(f'Registering blueprint={bp.name!r} pkg={bp.import_name!r} {bp.url_prefix=!r} {bp.subdomain=!r}')
            self._app.register_blueprint(bp)

        add_context_filter(UniqueIdFilter(), self._app.logger.name)

    def start_server(self):
        raise NotImplementedError

    def stop_server(self):
        raise NotImplementedError


class UniqueIdFilter(logging.Filter):
    def filter(self, record):
        if not getattr(record, 'uid', None):
            record.uid = getattr(wz_local, 'uid', '-')
        return True


def init_logging(log_path, verbose=0, pid=False, log_fmt=None, **kwargs):
    logging.getLogger('py.warnings')  # Make sure this logger exists before adding the uid filter
    add_context_filter(UniqueIdFilter())
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
    log.info(f'Beginning request for {ip=} {user=} {method=} {path=} {qs=!r} {referrer=!r}')


@base.after_app_request
def after_requests(response: Response):
    duration = time.monotonic() - wz_local.time
    user = request.remote_user or '-'
    method = request.method
    path = request.path
    code = response.status_code
    size = response.content_length
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
        'request.headers': {k: request.headers[k] for k in sorted(request.headers)},
    }
    return Response(Template(debug_table_template).render(tables=tables))
