"""
Helpers for serializing Python data structures to JSON or YAML

:author: Doug Skrypa
"""

import json
from base64 import b64encode
from collections import UserDict
from collections.abc import Mapping, KeysView, ValuesView
from datetime import datetime, date, timedelta
from traceback import format_tb
from types import TracebackType

import yaml

__all__ = ['IndentedYamlDumper', 'PermissiveJSONEncoder', 'prep_for_yaml', 'yaml_dump']


class PermissiveJSONEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, (set, KeysView)):
            return sorted(o)
        elif isinstance(o, ValuesView):
            return list(o)
        elif isinstance(o, Mapping):
            return dict(o)
        elif isinstance(o, bytes):
            try:
                return o.decode('utf-8')
            except UnicodeDecodeError:
                return b64encode(o).decode('utf-8')
        elif isinstance(o, datetime):
            return o.strftime('%Y-%m-%d %H:%M:%S %Z')
        elif isinstance(o, date):
            return o.strftime('%Y-%m-%d')
        elif isinstance(o, (type, timedelta)):
            return str(o)
        elif isinstance(o, TracebackType):
            return ''.join(format_tb(o)).splitlines()
        elif hasattr(o, '__to_json__'):
            return o.__to_json__()
        elif hasattr(o, '__serializable__'):
            return o.__serializable__()
        return super().default(o)


class IndentedYamlDumper(yaml.SafeDumper):
    """This indents lists that are nested in dicts in the same way as the Perl yaml library"""
    def increase_indent(self, flow=False, indentless=False):
        return super().increase_indent(flow, False)


def prep_for_yaml(obj):
    if isinstance(obj, UserDict):
        obj = obj.data
    # noinspection PyTypeChecker
    if isinstance(obj, Mapping):
        return {prep_for_yaml(k): prep_for_yaml(v) for k, v in obj.items()}
    elif isinstance(obj, (set, KeysView)):
        return [prep_for_yaml(v) for v in sorted(obj)]
    elif isinstance(obj, (list, tuple, map, ValuesView)):
        return [prep_for_yaml(v) for v in obj]
    elif isinstance(obj, bytes):
        return obj.decode('utf-8')
    elif isinstance(obj, datetime):
        return obj.strftime('%Y-%m-%d %H:%M:%S %Z')
    elif isinstance(obj, date):
        return obj.strftime('%Y-%m-%d')
    elif isinstance(obj, (type, timedelta)):
        return str(obj)
    else:
        return obj


def yaml_dump(data, force_single_yaml=False, indent_nested_lists=False, default_flow_style=None, **kwargs):
    """
    Serialize the given data as YAML

    :param data: Data structure to be serialized
    :param bool force_single_yaml: Force a single YAML document to be created instead of multiple ones when the
      top-level data structure is not a dict
    :param bool indent_nested_lists: Indent lists that are nested in dicts in the same way as the Perl yaml library
    :return str: Yaml-formatted data
    """
    content = prep_for_yaml(data)
    kwargs.setdefault('explicit_start', True)
    kwargs.setdefault('width', float('inf'))
    kwargs.setdefault('allow_unicode', True)
    if indent_nested_lists:
        kwargs['Dumper'] = IndentedYamlDumper

    if isinstance(content, (dict, str)) or force_single_yaml:
        kwargs.setdefault('default_flow_style', False if default_flow_style is None else default_flow_style)
        formatted = yaml.dump(content, **kwargs)
    else:
        kwargs.setdefault('default_flow_style', True if default_flow_style is None else default_flow_style)
        formatted = yaml.dump_all(content, **kwargs)
    if formatted.endswith('...\n'):
        formatted = formatted[:-4]
    if formatted.endswith('\n'):
        formatted = formatted[:-1]
    return formatted
