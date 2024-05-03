"""

"""

import json
import inspect
from pprint import pprint
from traceback import format_stack

from werkzeug.exceptions import HTTPException
from werkzeug.utils import escape

from ..output.printer import PseudoJsonEncoder

__all__ = ['patch_http_exception']

_http_exc_init = HTTPException.__init__


def patch_http_exception():
    HTTPException.__init__ = http_exc_init
    HTTPException.get_body = http_exc_get_body


def _format(data):
    try:
        return json.dumps(data, sort_keys=True, indent=4, cls=PseudoJsonEncoder, ensure_ascii=False)
    except Exception:  # noqa
        return pprint(data)


def http_exc_get_body(self, environ=None, scope=None):
    name = escape(self.name)
    if isinstance(self.description, str) and self.description.startswith('<pre>'):
        description = self.description
    else:
        description = self.get_description(environ)

    return (
        '<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 3.2 Final//EN">\n'
        f'<title>{self.code} {name}</title>\n'
        f'<h1>{self.code} {name}</h1>\n'
        f'{description}\n'
        f'<h2>Stack Trace</h2>\n'
        f'<pre>{escape(self._stack)}</pre>\n'
        '<br/><br/>\n'
        '<h2>Locals</h2>\n'
        f'<pre>{escape(self._locals)}</pre>\n'
    )


def http_exc_init(self, *args, **kwargs):
    stack = inspect.stack()
    self._locals = _format({f'{i}: {fi.function}': fi.frame.f_locals for i, fi in enumerate(stack[1:6])})
    self._stack = ''.join(format_stack())
    _http_exc_init(self, *args, **kwargs)
