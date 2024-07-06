"""
Output formatting functions

:author: Doug Skrypa
"""

from __future__ import annotations

import logging
import re
from math import log as math_log

from struct import calcsize, unpack_from, error as StructError
from typing import TYPE_CHECKING, Mapping, Sized, Iterable, Container, Iterator, Collection, Any, Callable

from .color import colored

if TYPE_CHECKING:
    from datetime import timedelta
    from ..core.typing import Bool

__all__ = [
    'format_output',
    'format_percent',
    'format_tiered',
    'pseudo_yaml',
    'readable_bytes',
    'short_repr',
    'bullet_list',
    'to_hex_and_str',
    'collapsed_ranges_str',
    'collapse_ranges',
    'format_duration',
    'timedelta_to_str',
    'ordinal_suffix',
]
log = logging.getLogger(__name__)


def short_repr(
    obj: Any,
    when_gt: int = 100,
    parts: int = 45,
    sep: str = '...',
    func: Callable[[Any], str] = repr,
    containers_only: Bool = True,
) -> str:
    obj_repr = func(obj)
    if containers_only and not isinstance(obj, Container):
        return obj_repr
    if len(obj_repr) > when_gt:
        return f'{obj_repr[:parts]}{sep}{obj_repr[-parts:]}'
    return obj_repr


def readable_bytes(
    size: float | int,
    dec_places: int = None,
    dec_by_unit: Mapping[str, int] = None,
    si: Bool = False,
    bits: Bool = False,
    i: Bool = False,
    rate: bool | str = False,
) -> str:
    """
    :param size: The number of bytes to render as a human-readable string
    :param dec_places: Number of decimal places to include (overridden by dec_by_unit if specified)
    :param dec_by_unit: Mapping of {unit: number of decimal places to include}
    :param si: Use the International System of Units (SI) definition (base-10) instead of base-2 (default: base-2)
    :param bits: Use lower-case ``b`` instead of ``B``
    :param i: Include the ``i`` before ``B`` to indicate that this suffix is based on the base-2 value (this only
      affects the unit in the string - use ``si=True`` to use base-10)
    :param rate: Whether the unit is a rate or not.  If True, ``/s`` will be appended to the unit.  If a string is
      provided, that string will be appended instead.
    """
    units = ('B ', 'KB', 'MB', 'GB', 'TB', 'PB', 'EB', 'ZB', 'YB')  # len=9 @ YB -> max exp = 8
    kilo = 1000 if si else 1024
    abs_size = abs(size)
    try:
        exp = min(int(math_log(abs_size, kilo)), 8) if abs_size > 0 else 0  # update 8 to len-1 if units are added
    except TypeError as e:
        raise ValueError(f'Invalid {size=}') from e

    unit = units[exp]
    if dec_places is not None:
        dec = dec_places
    elif dec_by_unit and isinstance(dec_by_unit, dict):
        dec = dec_by_unit.get(unit, 2)
    else:
        dec = 2 if exp else 0

    if bits:
        unit = unit.replace('B', 'b')
    if i and exp and not si:  # no `i` is necessary for B/b
        unit = unit[0] + 'i' + unit[1]
    if rate:
        unit = unit.strip() + ('/s' if rate is True else rate) + ('' if exp else ' ')  # noqa
    return f'{size / kilo ** exp:,.{dec}f} {unit}'


def format_percent(num: float | int, div: float | int) -> str:
    return f'{num / div:,.2%}' if div > 0 else '--.--%'


def format_output(text: str, should_color: bool, color_str: str, width: int = None, justify: str = None) -> str:
    """
    Pad output with spaces to work around ansi colors messing with normal string formatting width detection

    :param text: Text to format
    :param should_color: Do apply color_str color
    :param color_str: Color to use
    :param width: Column width (for padding)
    :param justify: Left or Right (default: right)
    :return: Formatted output
    """
    if width is not None:
        padding = ' ' * (width - len(text))
        j = justify[0].upper() if justify is not None else 'L'
        text = text + padding if j == 'L' else padding + text
    if should_color:
        return colored(text, color_str)
    return text


def format_tiered(obj, sort_keys: Bool = True) -> list[str]:
    lines = []
    if isinstance(obj, dict):
        if len(obj) < 1:
            return format_tiered('{}')
        kw = max(len(k) for k in obj)
        pad = ' ' * kw
        items = sorted(obj.items()) if sort_keys else obj.items()
        for key, val in items:
            fk = key.ljust(kw)
            for i, sub_obj in enumerate(format_tiered(val)):
                lines.append(f'{fk}:  {sub_obj}' if not i else f'{pad}   {sub_obj}')
    elif isinstance(obj, list):
        if len(obj) < 1:
            return format_tiered('[]')
        kw = len(str(len(obj)))
        pad = ' ' * kw
        fmt = '[{{:>{}}}]:  {{}}'.format(kw)
        for i, item in enumerate(obj):
            for j, sub_obj in enumerate(format_tiered(item)):
                lines.append(fmt.format(i, sub_obj) if not j else f' {pad}    {sub_obj}')
    else:
        try:
            lines.append(str(obj))
        except Exception:  # noqa
            lines.append(obj)
    return lines


def pseudo_yaml(obj, indent: int = 4, sort_keys: Bool = True) -> list[str]:
    lines = []
    if isinstance(obj, Mapping):
        if len(obj) < 1:
            return pseudo_yaml('{}', indent)
        pad = ' ' * indent
        items = sorted(obj.items()) if sort_keys else obj.items()
        for key, val in items:
            fk = key.ljust(indent)
            if isinstance(val, str):
                if '\n' in val:
                    lines.append(f'{fk}:')
                    lines.extend(f'{pad}{line}' for line in val.splitlines())
                else:
                    lines.append(f'{fk}: {val}')
            elif isinstance(val, (Mapping, Sized, Iterable, Container)):
                lines.append(f'{fk}:')
                lines.extend(f'{pad}{sub_obj}' for sub_obj in pseudo_yaml(val, indent))
            else:
                lines.append(f'{fk}: {val}')
    elif all(isinstance(obj, abc_type) for abc_type in (Sized, Iterable, Container)):
        if len(obj) < 1:
            return pseudo_yaml('[]', indent)
        pad = ' ' * indent
        fmt_a = f'{pad}- {{}}'
        fmt_b = f'{pad}  {{}}'
        for val in obj:
            if isinstance(val, (Mapping, Sized, Iterable, Container)):
                sub_objs = val.splitlines() if isinstance(val, str) else pseudo_yaml(val, indent)
                lines += [fmt_b.format(sub_obj) if j else fmt_a.format(sub_obj) for j, sub_obj in enumerate(sub_objs)]
            else:
                lines.append(fmt_a.format(val))
    else:
        try:
            lines.append(str(obj))
        except UnicodeEncodeError as e:
            lines.append(obj)
    return lines


def bullet_list(data: Collection[Any], bullet: str = '-', indent: int = 2, sort: bool = True):
    if sort:
        data = sorted(data)
    prefix = ' ' * indent + bullet
    return '\n'.join(f'{prefix} {line}' for line in data)


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
        if struct is repr:
            from_struct = data
        else:
            from_struct = []
            for i in range(offset, len(data), calcsize(struct)):
                try:
                    from_struct.extend(unpack_from(struct, data, i))
                except StructError:
                    pass
        return f'{pre} {as_hex}  |  {as_str}  |  {from_struct}'
    return f'{pre} {as_hex}  |  {as_str}'


def collapsed_ranges_str(values: Iterable[str], sep: str = '...', delim: str = ', ') -> str:
    """
    Collapse the given values using :func:`collapse_ranges` and return a string that represents the sorted results.
    Standalone values are included verbatim, and ranges are collapsed to show the first and last values with the
    specified separator.

    :param values: Strings with common prefixes ending with integers
    :param sep: The separator to use between the first and last element in each range (default: ``...``)
    :param delim: The delimiter between ranges / standalone values (default: ``, ``)
    :return: String representing the given values
    """
    return delim.join(start if start == end else f'{start}{sep}{end}' for start, end in collapse_ranges(values))


def collapse_ranges(values: Iterable[str]) -> list[tuple[str, str]]:
    try:
        match_suffix = collapse_ranges._match_suffix
    except AttributeError:
        collapse_ranges._match_suffix = match_suffix = re.compile(r'^(.*?)(\d+)$').match

    groups = []
    with_suffix = {}
    for value in values:
        if m := match_suffix(value):
            prefix, suffix = m.groups()
            with_suffix[value] = (prefix, int(suffix))
        else:
            groups.append((value, value))

    group = {}
    last = None
    for value, (prefix, suffix) in sorted(with_suffix.items(), key=lambda kv: kv[1]):
        if prefix != last and group:
            groups.extend(_collapse_ranges(group))
            group = {}

        group[value] = suffix
        last = prefix

    if group:
        groups.extend(_collapse_ranges(group))

    groups.sort()
    return groups


def _collapse_ranges(values: dict[str, int]) -> Iterator[tuple[str, str]]:
    start, end, last = None, None, None
    for value, suffix in values.items():
        if start is None:
            start = end = value
        elif suffix - last == 1:
            end = value
        else:
            yield start, end
            start = end = value

        last = suffix

    if start is not None:
        yield start, end


def format_duration(seconds: float) -> str:
    """
    Formats time in seconds as (Dd)HH:MM:SS (time.stfrtime() is not useful for formatting durations).

    :param seconds: Number of seconds to format
    :return: Given number of seconds as (Dd)HH:MM:SS
    """
    x = '-' if seconds < 0 else ''
    m, s = divmod(abs(seconds), 60)
    h, m = divmod(int(m), 60)
    d, h = divmod(h, 24)
    x = f'{x}{d}d' if d > 0 else x

    if isinstance(s, int):
        return f'{x}{h:02d}:{m:02d}:{s:02d}'
    return f'{x}{h:02d}:{m:02d}:{s:05.2f}'


def timedelta_to_str(delta: timedelta) -> str:
    m, s = divmod(delta.seconds, 60)
    h, m = divmod(m, 60)
    td_str = f'{h:d}:{m:02d}:{s:02d}'
    if delta.days != 0:
        td_str = f'{delta.days:d}d, {td_str}'
    return td_str


def ordinal_suffix(num: int) -> str:
    """
    Returns the ordinal suffix (st, nd, rd, th) that should be used for the given base-10 integer.
    Handles both positive and negative integers.
    Correctly handles values such as 111th - 113rd with any value in the hundreds place.
    """
    # While it may be slightly cleaner to use `num = abs(num)` and to store `tens = num % 100` before the if/elif
    # block, profiling revealed the below approach to be the fastest compared to approaches using those alternatives.
    if num < 0:
        num = -num
    ones = num % 10
    if not ones or ones > 3:
        return 'th'
    elif ones == 1:
        return 'th' if num % 100 == 11 else 'st'
    elif ones == 2:
        return 'th' if num % 100 == 12 else 'nd'
    else:  # ones == 3
        return 'th' if num % 100 == 13 else 'rd'
