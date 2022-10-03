"""
The Printer class and helper functions for it.  Provides a centralized interface for serializing Python data structures
in a way that users may choose the output format of scripts at runtime.

:author: Doug Skrypa
"""

import json
import logging
import pprint
import types
from collections.abc import Mapping, Sized, Iterable, Container

try:
    from win32com.client import DispatchBaseClass
    from ..windows.com.utils import com_repr
except ImportError:
    DispatchBaseClass = None
    com_repr = None

from ..core.serialization import PermissiveJSONEncoder, yaml_dump
from .constants import PRINTER_FORMATS
from .formatting import format_tiered, pseudo_yaml
from .repr import print_rich_repr, rich_repr
from .table import Table
from .terminal import uprint

__all__ = ['Printer']
log = logging.getLogger(__name__)

_FORMAT_HANDLERS = {}


def print_tiered(obj):
    for line in format_tiered(obj):
        uprint(line)


def format_handler(name: str):
    def register_format_handler(func):
        _FORMAT_HANDLERS[name] = func
        return func
    return register_format_handler


class Printer:
    __slots__ = ('output_format', 'uprint')
    handlers = _FORMAT_HANDLERS
    formats = PRINTER_FORMATS

    def __init__(self, output_format: str, uprint: bool = False):  # noqa
        if output_format is None or output_format in Printer.formats:
            self.output_format = output_format
            self.uprint = uprint
        else:
            raise ValueError(f'Invalid output format={output_format!r} (valid options: {self.formats})')

    def pformat(self, content, *args, **kwargs):
        if isinstance(content, types.GeneratorType):
            return '\n'.join(self.pformat(c, *args, **kwargs) for c in content)
        try:
            handler = self.handlers[self.output_format]
        except KeyError:
            return content
        else:
            return handler(content)

    def pprint(self, content, *args, gen_empty_error=None, **kwargs):
        if isinstance(content, types.GeneratorType):
            i = 0
            for c in content:
                self.pprint(c, *args, **kwargs)
                i += 1

            if (i == 0) and gen_empty_error:
                log.error(gen_empty_error)
        elif self.output_format in ('csv', 'table'):
            kwargs['mode'] = self.output_format
            try:
                Table.auto_print_rows(content, *args, **kwargs)
            except AttributeError:
                raise ValueError(f'Invalid content format to be formatted as a {self.output_format}')
        elif self.output_format == 'rich':
            print_rich_repr(content)
        else:
            print_func = uprint if self.uprint else print
            print_func(self.pformat(content, *args, **kwargs))

    @staticmethod
    @format_handler('json-compact')
    def jsonc(content, *args, **kwargs):
        return json.dumps(content, separators=(',', ':'), cls=PermissiveJSONEncoder, ensure_ascii=False)

    @staticmethod
    @format_handler('json')
    def json(content, *args, **kwargs):
        return json.dumps(content, cls=PermissiveJSONEncoder, ensure_ascii=False)

    @staticmethod
    @format_handler('json-pretty')
    def jsonp(content, *args, **kwargs):
        return json.dumps(content, sort_keys=True, indent=4, cls=PermissiveJSONEncoder, ensure_ascii=False)

    @format_handler('pseudo-json')
    def pseudo_json(self, content, *args, **kwargs):
        return json.dumps(content, sort_keys=True, indent=4, cls=PseudoJsonEncoder, ensure_ascii=False)

    @format_handler('json-lines')
    def json_lines(self, content, *args, **kwargs):
        if not isinstance(content, (list, set)):
            raise TypeError('Expected list or set; found {}'.format(type(content).__name__))
        lines = ['[']
        last = len(content) - 1
        for i, val in enumerate(content):
            suffix = ',' if i < last else ''
            lines.append(json.dumps(val, cls=PermissiveJSONEncoder, ensure_ascii=False) + suffix)
        lines.append(']\n')
        return '\n'.join(lines)

    @format_handler('text')
    def text(self, content, *args, **kwargs):
        return '\n'.join(format_tiered(content))

    @format_handler('plain')
    def plain(self, content, *args, **kwargs):
        if isinstance(content, str):
            return content
        elif isinstance(content, Mapping):
            return '\n'.join(f'{k}: {v}' for k, v in sorted(content.items()))
        elif all(isinstance(content, abc_type) for abc_type in (Sized, Iterable, Container)):
            return '\n'.join(sorted(map(str, content)))
        else:
            return str(content)

    @format_handler('pseudo-yaml')
    def pseudo_yaml(self, content, *args, **kwargs):
        return '\n'.join(pseudo_yaml(content))

    @format_handler('yaml')
    def yaml(self, content, *args, **kwargs):
        return yaml_dump(
            content,
            kwargs.pop('force_single_yaml', False),
            kwargs.pop('indent_nested_lists', True),
            sort_keys=kwargs.pop('sort_keys', True),
        )

    @format_handler('pprint')
    def pprint_format(self, content, *args, **kwargs):
        return pprint.pformat(content)

    @format_handler('csv')
    @format_handler('table')
    def tabular(self, content, *args, **kwargs):
        kwargs['mode'] = self.output_format
        try:
            return Table.auto_format_rows(content, *args, **kwargs)
        except AttributeError:
            raise ValueError(f'Invalid content format to be formatted as a {self.output_format}')

    @format_handler('rich')
    def rich(self, content, *args, **kwargs):
        return rich_repr(content)


class PseudoJsonEncoder(PermissiveJSONEncoder):
    def default(self, o):
        if DispatchBaseClass is not None and isinstance(o, DispatchBaseClass):
            return com_repr(o)
        try:
            return super().default(o)
        except TypeError:
            return repr(o)
        except UnicodeDecodeError:
            return o.decode('utf-8', 'replace')


del _FORMAT_HANDLERS
