"""
ANSI Color Handling (originally based on the 'colored' module)

:author: Doug Skrypa
"""

from typing import Union, Any, Iterable

from ._colors import ANSI_COLORS, ANSI_COLORS_REVERSE, HEX_COLORS_REVERSE, ANSI_ATTRS, FG_PREFIX, BG_PREFIX

__all__ = ['colored', 'InvalidAnsiCode']

C = Union[str, int]
Attrs = Union[C, Iterable[C]]
Bool = Union[bool, Any]


def colored(
    text: Any, color: C = None, bg_color: C = None, attrs: Attrs = None, reset: Bool = True, *, prefix: C = None
) -> str:
    if not text:
        return ''
    if color is bg_color is attrs is prefix is None:
        return text
    parts = (
        f'\x1b[{prefix}m' if prefix else '',
        ansi_color_code(color, FG_PREFIX) if color is not None else '',
        ansi_color_code(bg_color, BG_PREFIX) if bg_color is not None else '',
        attr_code(attrs) if attrs is not None else '',
        str(text) if not isinstance(text, str) else text,
        '\x1b[0m' if reset else ''
    )
    return ''.join(parts)


def attr_code(attr: Attrs) -> str:
    if isinstance(attr, (str, int)):
        try:
            return ANSI_ATTRS[attr]
        except KeyError as e:
            raise InvalidAnsiCode(attr) from e
    else:
        try:
            return ''.join(ANSI_ATTRS[a] for a in attr)
        except Exception as e:
            raise InvalidAnsiCode(attr) from e


def fg_color_code(color: C) -> str:
    return ansi_color_code(color, FG_PREFIX)


def bg_color_code(color: C) -> str:
    return ansi_color_code(color, BG_PREFIX)


def ansi_color_code(color: C, base: C) -> str:
    color = str(color)
    if color in ANSI_COLORS_REVERSE:
        return f'\x1b[{base}{color}m'

    color_map = HEX_COLORS_REVERSE if color.startswith('#') else ANSI_COLORS
    try:
        color_num = color_map[color.lower()]
    except KeyError as e:
        raise InvalidAnsiCode(color) from e
    else:
        return f'\x1b[{base}{color_num}m'


class InvalidAnsiCode(ValueError):
    """Exception to be raised when an invalid ANSI color/attribute code is selected"""
