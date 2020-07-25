"""
Utilities for running Flask servers with gunicorn

When using gevent workers, the following lines should be the first lines of code in the top-level script (after the
shebang and any docstrings, but before any other imports)::\n
    if __name__ == '__main__':
        from gevent import monkey
        monkey.patch_all()

:author: Doug Skrypa
"""

import logging
import os
import signal
import sys
from traceback import format_exc
from typing import Optional, MutableMapping, Any

from gunicorn import debug, util
from gunicorn.app.base import Application
from gunicorn.arbiter import Arbiter

from .server import FlaskServer

__all__ = ['GunicornServer']
log = logging.getLogger(__name__)


class GunicornServer(FlaskServer, Application):
    """
    This class kets the Gunicorn server be started from within Python without needing to use the gunicorn CLI.  This
    implementation is based on the Custom Application documentation.

    .. important::
        The ``gunicorn_cfg`` must include ``{'workers': 1}`` or above, which will result in an additional worker
        **process** being spawned.  Using 0 workers will result in a mester process with no workers to handle incoming
        requests.
    """

    def __init__(self, *args, gunicorn_cfg: Optional[MutableMapping[str, Any]] = None, **kwargs):
        self._cfg = gunicorn_cfg or {}
        self._cfg.setdefault('worker_class', 'gevent')
        self._cfg.setdefault('workers', 1)
        FlaskServer.__init__(self, *args, **kwargs)
        Application.__init__(self)
        self._arbiter = None

    def load_config(self):
        self._cfg.setdefault('bind', f'{self._host}:{self._port}')
        for key, val in self._cfg.items():
            self.cfg.set(key.lower(), val)

    def init(self, parser, opts, args):
        pass

    def load(self):
        return self._app

    def start_server(self):
        """
        Combined + slightly cleaned up version of gunicorn.app.base.Application and gunicorn.app.base.BaseApplication.
        This is only done so that a ref to the Arbiter used to run the application can be stored, which is needed to
        programmatically initiate graceful shutdown.
        """
        if self.cfg.check_config:
            try:
                self.load()
            except BaseException:  # gunicorn used a bare except:
                print(f'\nError while loading the application:\n{format_exc()}', file=sys.stderr, flush=True)
                sys.exit(1)
            sys.exit(0)
        if self.cfg.spew:
            debug.spew()
        if self.cfg.daemon:
            util.daemonize(self.cfg.enable_stdio_inheritance)
        # set python paths
        if self.cfg.pythonpath:
            paths = self.cfg.pythonpath.split(",")
            for path in paths:
                pythonpath = os.path.abspath(path)
                if pythonpath not in sys.path:
                    sys.path.insert(0, pythonpath)

        log.info(f'Starting Flask app={self._app.name!r} on port={self._port}', extra={'color': 14})
        self._arbiter = Arbiter(self)
        try:
            self._arbiter.run()
        except RuntimeError as e:
            print(f'\nError: {e}', file=sys.stderr, flush=True)
            sys.exit(1)

    def stop_server(self):
        """
        Signal this app's Arbiter with SIGTERM so that its gunicorn.arbiter.Arbiter.run method gracefully initiates a
        shutdown from within the context that it usually would.

        It could be achieved without the copying of run methods into :meth:`.start_server`, by just appending SIGTERM to
        the Arbiter class's SIG_QUEUE because it is defined as a class property, but its PIPE property is overwritten on
        instances, so the gunicorn.arbiter.Arbiter.wakeup functionality requires a reference to the instance of Arbiter
        that is being used for this app.
        """
        self._arbiter.signal(signal.SIGTERM, None)
