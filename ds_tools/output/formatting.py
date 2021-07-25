"""
Output formatting functions

:author: Doug Skrypa
"""

import logging
import math
from collections import OrderedDict
from struct import calcsize, unpack_from, error as StructError
from typing import Union, Mapping, Sized, Iterable, Container

from .color import colored

__all__ = [
    'format_output',
    'format_percent',
    'format_tiered',
    'pseudo_yaml',
    'readable_bytes',
    'to_bytes',
    'to_str',
    'short_repr',
    'bullet_list',
    'to_hex_and_str',
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


def short_repr(obj, when_gt=100, parts=45, sep='...', func=repr, containers_only=True):
    obj_repr = func(obj)
    if containers_only and not isinstance(obj, Container):
        return obj_repr
    if len(obj_repr) > when_gt:
        return '{}{}{}'.format(obj_repr[:parts], sep, obj_repr[-parts:])
    return obj_repr


def readable_bytes(size: Union[float, int], dec_places: int = None, dec_by_unit: Mapping[str, int] = None):
    """
    :param size: The number of bytes to render as a human-readable string
    :param dec_places: Number of decimal places to include (overridden by dec_by_unit if specified)
    :param dec_by_unit: Mapping of {unit: number of decimal places to include}
    :return:
    """
    units = list(zip(['B ', 'KB', 'MB', 'GB', 'TB', 'PB', 'EB', 'ZB', 'YB'], [0, 2, 2, 2, 2, 2, 2, 2, 2]))
    try:
        exp = min(int(math.log(abs(size), 1024)), len(units) - 1) if abs(size) > 0 else 0
    except TypeError as e:
        raise ValueError(f'Invalid {size=}') from e
    unit, dec = units[exp]
    if dec_places is not None:
        dec = dec_places
    if isinstance(dec_by_unit, dict):
        dec = dec_by_unit.get(unit, 2)
    return '{{:,.{}f}} {}'.format(dec, unit).format(size / 1024 ** exp)


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


def bullet_list(data, bullet='-', indent=2, sort=True):
    data = sorted(data) if sort else data
    fmt = '{}{} {{}}'.format(' ' * indent, bullet)
    return '\n'.join(fmt.format(line) for line in data)


def to_hex_and_str(
    pre, data: bytes, *, encoding: str = 'utf-8', fill: int = 0, struct: str = None, offset: int = 0, pad: bool = False
) -> str:
    """
    Format the given bytes to appear similar to the format used by xxd.  Intended to be called for each line - splitting
    the data into the amount to appear on each line should be done before calling this function.

    :param pre: Line prefix
    :param data: The binary data to be converted
    :param encoding: Encoding to use for the str portion
    :param fill: Ensure hex fills the amount of space that would be required for this many bytes
    :param struct: Interpret contents as an array of the given struct format character
    :param offset: Offset to apply before processing contents as a struct array
    :param pad: Pad the string portion to ensure alignment when escaped characters are found
    :return: String containing both the hex and str representations
    """
    try:
        replacements = to_hex_and_str._replacements
    except AttributeError:
        import sys
        from unicodedata import category
        repl_map = {c: '.' for c in map(chr, range(sys.maxunicode + 1)) if category(c) == 'Cc'}
        to_hex_and_str._replacements = replacements = str.maketrans(repl_map | {'\r': '\\r', '\n': '\\n', '\t': '\\t'})

    as_hex = data.hex(' ', -4)
    if pad:
        esc = {'\r', '\n', '\t'}
        as_str = ''.join(c if c in esc else f' {c}' for c in data.decode(encoding, 'replace')).translate(replacements)
    else:
        as_str = data.decode(encoding, 'replace').translate(replacements)
    if fill:
        if (to_fill := fill * 2 + (fill // 4) - 1 - len(as_hex)) > 0:
            as_hex += ' ' * to_fill
        if to_fill := fill * (1 + int(pad)) - len(as_str):
            as_str += ' ' * to_fill

    if struct:
        from_struct = []
        for i in range(offset, len(data), calcsize(struct)):
            try:
                from_struct.extend(unpack_from(struct, data, i))
            except StructError:
                pass
        return f'{pre} {as_hex}  |  {as_str}  |  {from_struct}'
    return f'{pre} {as_hex}  |  {as_str}'
