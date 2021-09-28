"""
Utilities for running Flask servers with gunicorn

When using gevent workers, the following lines should be the first lines of code in the top-level script (after the
shebang and any docstrings, but before any other imports)::\n
    if __name__ == '__main__':
        from gevent import monkey
        monkey.patch_all()

:author: Doug Skrypa
"""

import json
import logging
import os
import signal
from typing import Optional, MutableMapping, Any

from gunicorn.app.base import Application
from gunicorn.arbiter import Arbiter

from ..output.printer import PseudoJsonEncoder
from .server import FlaskServer, init_logging

__all__ = ['GunicornServer']
log = logging.getLogger(__name__)
ConfigDict = Optional[MutableMapping[str, Any]]


class GunicornServer(FlaskServer, Application):
    """
    This class kets the Gunicorn server be started from within Python without needing to use the gunicorn CLI.  This
    implementation is based on the Custom Application documentation.

    .. important::
        The ``gunicorn_cfg`` must include ``{'workers': 1}`` or above, which will result in an additional worker
        **process** being spawned.  Using 0 workers will result in a mester process with no workers to handle incoming
        requests.
    """

    def __init__(self, *args, gunicorn_cfg: ConfigDict = None, log_cfg: ConfigDict = None, **kwargs):
        self._log_cfg = log_cfg
        self._cfg = gunicorn_cfg or {}
        self._cfg.setdefault('worker_class', 'gevent')
        self._cfg.setdefault('workers', 1)
        self.__on_starting = self._cfg.get('on_starting')
        self._cfg['on_starting'] = self._on_starting
        if log_cfg:
            self._cfg['post_fork'] = self._init_logging
        FlaskServer.__init__(self, *args, **kwargs)
        Application.__init__(self)
        self._arbiter = None

    def load_config(self):
        self._cfg.setdefault('bind', f'{self._host}:{self._port}')
        for key, val in self._cfg.items():
            self.cfg.set(key.lower(), val)

    def _on_starting(self, arbiter: Arbiter):
        """
        Called by :meth:`Arbiter.start` during server initialization.  Stores a reference to the :class:`Arbiter
        <gunicorn.arbiter.Arbiter>` so it can be used to initiate graceful shutdown programmatically.

        If another ``on_starting`` function was provided at init, then it is called here.

        :param arbiter: The Arbiter for this application
        """
        self._arbiter = arbiter
        if self._debug:
            configs = {k: v.value for k, v in self.cfg.settings.items()}
            log.info(
                f'Starting Flask app={self._app.name!r} on port={self._port} with gunicorn '
                f'config={json.dumps(configs, indent=4, sort_keys=True, cls=PseudoJsonEncoder)}',
                extra={'color': 'cyan'}
            )
        else:
            log.info(f'Starting Flask app={self._app.name!r} on port={self._port}', extra={'color': 'cyan'})
        if self.__on_starting is not None:
            self.__on_starting(arbiter)

    def init(self, parser, opts, args):
        pass

    def load(self):
        return self._app

    def _init_logging(self, arbiter, worker):
        """
        Initializes logging.  Called by gunicorn as a post-fork function.

        Because gunicorn workers are separate processes, file logging needs to be initialized after forkingto prevent
        a race condition on file rotation.

        If ``log_path`` in the ``log_cfg`` provided to init contains ``{pid}``, then it will be replaced by the current
        process's pid.
        """
        log_cfg = self._log_cfg.copy()  # noqa
        if log_path := log_cfg.get('log_path'):
            log_cfg['log_path'] = log_path.format(pid=os.getpid())
        init_logging(**log_cfg)

    def start_server(self):
        super().run()

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
