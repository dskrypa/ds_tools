"""
Output formatting functions

:author: Doug Skrypa
"""

import json
import logging
import math
from collections import OrderedDict, UserDict
from collections.abc import Mapping, Sized, Iterable, Container, KeysView, ValuesView

import yaml

from .color import colored

__all__ = [
    'format_output', 'format_percent', 'format_tiered', 'IndentedYamlDumper', 'PermissiveJSONEncoder', 'prep_for_yaml',
    'pseudo_yaml', 'readable_bytes', 'to_bytes', 'to_str', 'yaml_dump'
]
log = logging.getLogger(__name__)


def to_bytes(data):
    if isinstance(data, str):
        return data.encode('utf-8')
    return data


def to_str(data):
    if isinstance(data, bytes):
        return data.decode('utf-8')
    return data


def readable_bytes(file_size):
    units = dict(zip(['B ', 'KB', 'MB', 'GB', 'TB', 'PB'], [0, 2, 2, 2, 2, 2]))
    try:
        exp = min(int(math.log(file_size, 1024)), len(units) - 1) if file_size > 0 else 0
    except TypeError as e:
        print('Invalid file size: {!r}'.format(file_size))
        raise e
    unit, dec = units[exp]
    return '{{:,.{}f}} {}'.format(dec, unit).format(file_size / 1024 ** exp)


def format_percent(num, div):
    return '{:,.2%}'.format(num, div) if div > 0 else '--.--%'


def format_output(text, should_color, color_str, width=None, justify=None):
    """
    Pad output with spaces to work around ansi colors messing with normal string formatting width detection

    :param str text: Text to format
    :param bool should_color: Do apply color_str color
    :param str color_str: Color to use
    :param int width: Column width (for padding)
    :param str justify: Left or Right (default: right)
    :return str: Formatted output
    """
    if width is not None:
        padding = ' ' * (width - len(text))
        j = justify[0].upper() if justify is not None else 'L'
        text = text + padding if j == 'L' else padding + text
    if should_color:
        return colored(text, color_str)
    return text


def format_tiered(obj):
    lines = []
    if isinstance(obj, dict):
        if len(obj) < 1:
            return format_tiered('{}')
        kw = max(len(k) for k in obj)
        pad = ' ' * kw

        key_list = obj.keys() if isinstance(obj, OrderedDict) else sorted(obj.keys())
        for k in key_list:
            fk = k.ljust(kw)
            sub_objs = format_tiered(obj[k])
            for i in range(len(sub_objs)):
                if i == 0:
                    lines.append('{}:  {}'.format(fk, sub_objs[i]))
                else:
                    lines.append('{}   {}'.format(pad, sub_objs[i]))
    elif isinstance(obj, list):
        if len(obj) < 1:
            return format_tiered('[]')
        kw = len(str(len(obj)))
        pad = ' ' * kw
        fmt = '[{{:>{}}}]:  {{}}'.format(kw)
        for i in range(len(obj)):
            sub_objs = format_tiered(obj[i])
            for j in range(len(sub_objs)):
                if j == 0:
                    lines.append(fmt.format(i, sub_objs[j]))
                else:
                    lines.append(' {}    {}'.format(pad, sub_objs[j]))
    else:
        try:
            lines.append(str(obj))
        except Exception as e:
            lines.append(obj)
    return lines


def pseudo_yaml(obj, indent=4):
    lines = []
    if isinstance(obj, Mapping):
        if len(obj) < 1:
            return pseudo_yaml('{}', indent)
        pad = ' ' * indent
        key_list = obj.keys() if isinstance(obj, OrderedDict) else sorted(obj.keys())
        for k in key_list:
            fk = k.ljust(indent)
            val = obj[k]
            if isinstance(val, (Mapping, Sized, Iterable, Container)):
                if isinstance(val, str):
                    if '\n' in val:
                        lines.append('{}:'.format(fk))
                        for line in val.splitlines():
                            lines.append('{}{}'.format(pad, line))
                    else:
                        lines.append('{}: {}'.format(fk, val))
                else:
                    lines.append('{}:'.format(fk))
                    for sub_obj in pseudo_yaml(val, indent):
                        lines.append('{}{}'.format(pad, sub_obj))
            else:
                lines.append('{}: {}'.format(fk, val))
    elif all(isinstance(obj, abc_type) for abc_type in (Sized, Iterable, Container)):
        if len(obj) < 1:
            return pseudo_yaml('[]', indent)
        pad = ' ' * indent
        fmtA = '{}- {{}}'.format(pad)
        fmtB = '{}  {{}}'.format(pad)
        for val in obj:
            if isinstance(val, (Mapping, Sized, Iterable, Container)):
                sub_objs = val.splitlines() if isinstance(val, str) else pseudo_yaml(val, indent)
                for j, sub_obj in enumerate(sub_objs):
                    if j == 0:
                        lines.append(fmtA.format(sub_obj))
                    else:
                        lines.append(fmtB.format(sub_obj))
            else:
                lines.append(fmtA.format(val))
    else:
        try:
            lines.append(str(obj))
        except UnicodeEncodeError as e:
            lines.append(obj)
    return lines


class PermissiveJSONEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, (set, KeysView)):
            return sorted(o)
        elif isinstance(o, ValuesView):
            return list(o)
        elif isinstance(o, Mapping):
            return dict(o)
        elif isinstance(o, bytes):
            return o.decode('utf-8')
        return super().default(o)


class IndentedYamlDumper(yaml.SafeDumper):
    """This indents lists that are nested in dicts in the same way as the Perl yaml library"""
    def increase_indent(self, flow=False, indentless=False):
        return super().increase_indent(flow, False)


def prep_for_yaml(obj):
    if isinstance(obj, UserDict):
        obj = obj.data
    if isinstance(obj, dict):
        return {prep_for_yaml(k): prep_for_yaml(v) for k, v in obj.items()}
    elif isinstance(obj, (list, set)):
        return [prep_for_yaml(v) for v in obj]
    else:
        return obj


def yaml_dump(data, force_single_yaml=False, indent_nested_lists=False):
    """
    Serialize the given data as YAML

    :param data: Data structure to be serialized
    :param bool force_single_yaml: Force a single YAML document to be created instead of multiple ones when the
      top-level data structure is not a dict
    :param bool indent_nested_lists: Indent lists that are nested in dicts in the same way as the Perl yaml library
    :return str: Yaml-formatted data
    """
    content = prep_for_yaml(data)
    kwargs = {'explicit_start': True, 'width': float('inf'), 'allow_unicode': True}
    if indent_nested_lists:
        kwargs['Dumper'] = IndentedYamlDumper

    if isinstance(content, (dict, str)) or force_single_yaml:
        kwargs['default_flow_style'] = False
        formatted = yaml.dump(content, **kwargs)
    else:
        formatted = yaml.dump_all(content, **kwargs)
    if formatted.endswith('...\n'):
        formatted = formatted[:-4]
    if formatted.endswith('\n'):
        formatted = formatted[:-1]
    return formatted
