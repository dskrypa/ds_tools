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

from ..core.serialization import PermissiveJSONEncoder, yaml_dump
from .formatting import format_tiered, pseudo_yaml
from .table import Table
from .terminal import uprint

__all__ = ['Printer']
log = logging.getLogger(__name__)


def print_tiered(obj):
    for line in format_tiered(obj):
        uprint(line)


class Printer:
    formats = [
        'json', 'json-pretty', 'json-compact', 'text', 'yaml', 'pprint', 'csv', 'table', 'pseudo-yaml', 'json-lines',
        'plain'
    ]

    def __init__(self, output_format):
        if output_format is None or output_format in Printer.formats:
            self.output_format = output_format
        else:
            raise ValueError('Invalid output format: {} (valid options: {})'.format(output_format, Printer.formats))

    @staticmethod
    def jsonc(content):
        return json.dumps(content, separators=(',', ':'), cls=PermissiveJSONEncoder, ensure_ascii=False)

    @staticmethod
    def json(content):
        return json.dumps(content, cls=PermissiveJSONEncoder, ensure_ascii=False)

    @staticmethod
    def jsonp(content):
        return json.dumps(content, sort_keys=True, indent=4, cls=PermissiveJSONEncoder, ensure_ascii=False)

    def pformat(self, content, *args, **kwargs):
        if isinstance(content, types.GeneratorType):
            return '\n'.join(self.pformat(c, *args, **kwargs) for c in content)
        elif self.output_format == 'json':
            return json.dumps(content, cls=PermissiveJSONEncoder, ensure_ascii=False)
        elif self.output_format == 'json-pretty':
            return json.dumps(content, sort_keys=True, indent=4, cls=PermissiveJSONEncoder, ensure_ascii=False)
        elif self.output_format == 'json-compact':
            return json.dumps(content, separators=(',', ':'), cls=PermissiveJSONEncoder, ensure_ascii=False)
        elif self.output_format == 'json-lines':
            if not isinstance(content, (list, set)):
                raise TypeError('Expected list or set; found {}'.format(type(content).__name__))
            lines = ['[']
            last = len(content) - 1
            for i, val in enumerate(content):
                suffix = ',' if i < last else ''
                lines.append(json.dumps(val, cls=PermissiveJSONEncoder, ensure_ascii=False) + suffix)
            lines.append(']\n')
            return '\n'.join(lines)
        elif self.output_format == 'text':
            return '\n'.join(format_tiered(content))
        elif self.output_format == 'plain':
            if isinstance(content, str):
                return content
            elif isinstance(content, Mapping):
                return '\n'.join('{}: {}'.format(k, v) for k, v in sorted(content.items()))
            elif all(isinstance(content, abc_type) for abc_type in (Sized, Iterable, Container)):
                return '\n'.join(sorted(map(str, content)))
            else:
                return str(content)
        elif self.output_format == 'pseudo-yaml':
            return '\n'.join(pseudo_yaml(content))
        elif self.output_format == 'yaml':
            return yaml_dump(content, kwargs.pop('force_single_yaml', False), kwargs.pop('indent_nested_lists', False))
        elif self.output_format == 'pprint':
            return pprint.pformat(content)
        elif self.output_format in ('csv', 'table'):
            kwargs['mode'] = self.output_format
            try:
                return Table.auto_format_rows(content, *args, **kwargs)
            except AttributeError:
                raise ValueError('Invalid content format to be formatted as a {}'.format(self.output_format))
        else:
            return content

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
                raise ValueError('Invalid content format to be formatted as a {}'.format(self.output_format))
        else:
            uprint(self.pformat(content, *args, **kwargs))
