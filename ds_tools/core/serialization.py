"""
Helpers for serializing Python data structures to JSON or YAML

:author: Doug Skrypa
"""

import json
from collections import UserDict
from collections.abc import Mapping, KeysView, ValuesView

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
