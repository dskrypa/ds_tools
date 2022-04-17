"""
Functions to facilitate printing a color-coded diff of two objects.

:author: Doug Skrypa
"""

import json
from difflib import SequenceMatcher, unified_diff
from typing import Optional

from ..core.serialization import PermissiveJSONEncoder, yaml_dump
from ..output.color import colored
from ..output.formatting import to_hex_and_str

__all__ = ['cdiff', 'cdiff_objs', 'unified_byte_diff', 'unified_obj_diff']


def cdiff(path1, path2, n: int = 3):
    with open(path1, 'r', encoding='utf-8') as f1, open(path2, 'r', encoding='utf-8') as f2:
        _cdiff(f1.read().splitlines(), f2.read().splitlines(), path1, path2, n=n)


def cdiff_objs(obj1, obj2, fmt: Optional[str] = 'yaml', n: int = 3):
    """
    Print a comparison of the given objects when serialized with the given output format

    :param obj1: A serializable object
    :param obj2: A serializable object
    :param fmt: An output format (one of: json, yaml, str)
    :param n: Number of lines of context to include
    """
    str1, str2 = _objs_to_strs(obj1, obj2, fmt)
    _cdiff(str1.splitlines(), str2.splitlines(), 'obj1', 'obj2', n=n)


def _objs_to_strs(obj1, obj2, fmt: Optional[str] = 'yaml') -> tuple[str, str]:
    if fmt == 'json':
        str1 = json.dumps(obj1, sort_keys=True, indent=4, cls=PermissiveJSONEncoder)
        str2 = json.dumps(obj2, sort_keys=True, indent=4, cls=PermissiveJSONEncoder)
    elif fmt in ('yaml', 'yml'):
        str1, str2 = yaml_dump(obj1), yaml_dump(obj2)
    elif fmt in (None, 'str'):
        str1, str2 = str(obj1), str(obj2)
    else:
        raise ValueError(f'Invalid cdiff format: {fmt!r}')

    return str1, str2


def _cdiff(a, b, name_a: str = '', name_b: str = '', n: int = 3):
    for i, line in enumerate(unified_diff(a, b, name_a, name_b, n=n, lineterm='')):
        if line.startswith('+') and i > 1:
            print(colored(line, 2))
        elif line.startswith('-') and i > 1:
            print(colored(line, 1))
        elif line.startswith('@@ '):
            print(colored(line, 6), end='\n\n')
        else:
            print(line)


def unified_obj_diff(
    obj1, obj2, fmt: Optional[str] = 'yaml', n: int = 3, lineterm: str = '', color: bool = True,
):
    str1, str2 = _objs_to_strs(obj1, obj2, fmt)
    a = str1.splitlines()
    b = str2.splitlines()
    for group in SequenceMatcher(None, a, b).get_grouped_opcodes(n):
        first, last = group[0], group[-1]
        file1_range = _format_range_unified(first[1], last[2])
        file2_range = _format_range_unified(first[3], last[4])
        range_str = f'@@ -{file1_range} +{file2_range} @@'
        range_str = colored(range_str, 6) if color else range_str
        print(f'{range_str} {lineterm}' if lineterm else range_str)

        for tag, i1, i2, j1, j2 in group:
            if tag == 'equal':
                for line in a[i1:i2]:
                    print(' ' + line)
                continue

            if tag == 'replace' and i1 == j1 and i2 == j2:
                for line_a, line_b in zip(a[i1:i2], b[j1:j2]):
                    if color:
                        print(colored('-' + line_a, 1))
                        print(colored('+' + line_b, 2))
                    else:
                        print(f'-{line_a}\n+{line_b}')
                continue

            if tag in {'replace', 'delete'}:
                for line in a[i1:i2]:
                    line_str = '-' + line
                    print(colored(line_str, 1) if color else line_str)
            if tag in {'replace', 'insert'}:
                for line in b[j1:j2]:
                    line_str = '+' + line
                    print(colored(line_str, 2) if color else line_str)


def unified_byte_diff(
    a: bytes, b: bytes, n: int = 3, lineterm: str = '', color: bool = True, per_line: int = 20, **kwargs
):
    offset_fmt = '{{}} 0x{{:0{}X}}:'.format(len(hex(max(len(a), len(b)))) - 2).format
    av = memoryview(a)
    bv = memoryview(b)
    a = [av[i: i + per_line] for i in range(0, len(a), per_line)]
    b = [bv[i: i + per_line] for i in range(0, len(b), per_line)]

    for group in SequenceMatcher(None, a, b).get_grouped_opcodes(n):
        first, last = group[0], group[-1]
        file1_range = _format_range_unified(first[1], last[2])
        file2_range = _format_range_unified(first[3], last[4])
        range_str = f'@@ -{file1_range} +{file2_range} @@'
        range_str = colored(range_str, 6) if color else range_str
        print(f'{range_str} {lineterm}' if lineterm else range_str)

        for tag, i1, i2, j1, j2 in group:
            if tag == 'equal':
                for i, line in enumerate(a[i1:i2], i1):
                    print(to_hex_and_str(offset_fmt(' ', i * per_line), line.tobytes(), fill=per_line, **kwargs))
                continue
            if tag in {'replace', 'delete'}:
                for i, line in enumerate(a[i1:i2], i1):
                    line_str = to_hex_and_str(offset_fmt('-', i * per_line), line.tobytes(), fill=per_line, **kwargs)
                    print(colored(line_str, 1) if color else line_str)
            if tag in {'replace', 'insert'}:
                for i, line in enumerate(b[j1:j2], j1):
                    line_str = to_hex_and_str(offset_fmt('+', i * per_line), line.tobytes(), fill=per_line, **kwargs)
                    print(colored(line_str, 2) if color else line_str)


def _format_range_unified(start: int, stop: int) -> str:
    """Convert range to the "ed" format. Copied from difflib"""
    # Per the diff spec at http://www.unix.org/single_unix_specification/
    beginning = start + 1     # lines start numbering with one
    length = stop - start
    if length == 1:
        return str(beginning)
    if not length:
        beginning -= 1        # empty ranges begin at line just before the range
    return f'{beginning},{length}'
