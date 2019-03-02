"""
Functions to facilitate printing a color-coded diff of two objects.

:author: Doug Skrypa
"""

import json
from subprocess import Popen
from tempfile import NamedTemporaryFile

from ..core import PermissiveJSONEncoder, yaml_dump

__all__ = ['cdiff', 'cdiff_objs']


def cdiff(path1, path2):
    bash_cmd = [
        'diff',
        '--old-group-format=$\'%df-%dl Removed:\n\e[0;31m%<\e[0m\'',
        '--new-group-format=$\'%df-%dl Added:\n\e[0;32m%<\e[0m\'',
        '--unchanged-group-format= -ts {} {}'.format(path1, path2)
    ]
    p = Popen(['bash', '-c', ' '.join(bash_cmd)])
    return p.wait()


def cdiff_objs(obj1, obj2, fmt='yaml'):
    """
    Print a comparison of the given objects when serialized with the given output format

    :param obj1: A serializable object
    :param obj2: A serializable object
    :param str fmt: An output format (one of: json, yaml, str)
    """
    if fmt == 'json':
        str1 = json.dumps(obj1, sort_keys=True, indent=4, cls=PermissiveJSONEncoder)
        str2 = json.dumps(obj2, sort_keys=True, indent=4, cls=PermissiveJSONEncoder)
    elif fmt in ('yaml', 'yml'):
        str1, str2 = yaml_dump(obj1), yaml_dump(obj2)
    elif fmt in (None, 'str'):
        str1, str2 = str(obj1), str(obj2)
    else:
        raise ValueError('Invalid cdiff format: {!r}'.format(fmt))

    with NamedTemporaryFile() as temp1:
        with NamedTemporaryFile() as temp2:
            temp1.write(str1.encode('utf-8'))
            temp1.seek(0)
            temp2.write(str2.encode('utf-8'))
            temp2.seek(0)
            return cdiff(temp1.name, temp2.name)
