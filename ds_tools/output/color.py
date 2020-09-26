"""
ANSI Color Handling (originally based on the 'colored' module)

:author: Doug Skrypa
"""

__all__ = ['colored', 'InvalidAnsiCode']


def colored(text, color=None, bg_color=None, attrs=None, reset=True, *, prefix=None):
    parts = (
        f'\x1b[{prefix}m' if prefix else '',
        fg_color_code(color) if color is not None else '',
        bg_color_code(bg_color) if bg_color is not None else '',
        attr_code(attrs) if attrs is not None else '',
        text,
        '\x1b[0m' if reset else ''
    )
    return ''.join(parts)


def attr_code(attr):
    try:
        attrs = attr_code._attrs
    except AttributeError:
        # fmt: off
        attrs = attr_code._attrs = {
            'bold': '\x1b[1m',              1: '\x1b[1m',
            'dim': '\x1b[2m',               2: '\x1b[2m',
            'underlined': '\x1b[4m',        4: '\x1b[4m',
            'blink': '\x1b[5m',             5: '\x1b[5m',
            'reverse': '\x1b[7m',           7: '\x1b[7m',
            'hidden': '\x1b[8m',            8: '\x1b[8m',
            'reset': '\x1b[0m',             0: '\x1b[0m',
            'res_bold': '\x1b[21m',         21: '\x1b[21m',
            'res_dim': '\x1b[22m',          22: '\x1b[22m',
            'res_underlined': '\x1b[24m',   24: '\x1b[24m',
            'res_blink': '\x1b[25m',        25: '\x1b[25m',
            'res_reverse': '\x1b[27m',      27: '\x1b[27m',
            'res_hidden': '\x1b[28m',       28: '\x1b[28m',
        }
        # fmt: on

    if isinstance(attr, (str, int)):
        try:
            return attrs[attr]
        except KeyError as e:
            raise InvalidAnsiCode(attr) from e
    else:
        try:
            return ''.join(attrs[a] for a in attr)
        except Exception as e:
            raise InvalidAnsiCode(attr) from e


def fg_color_code(color):
    return ansi_color_code(color, '38;5;')


def bg_color_code(color):
    return ansi_color_code(color, '48;5;')


def ansi_color_code(color, base):
    color = str(color)
    code = '\x1b[' + base
    try:
        ansi_codes, ansi_rev, hex_rev = ansi_color_code._codes
    except AttributeError:
        from ._colors import ANSI_COLORS, ANSI_COLORS_REVERSE, HEX_COLORS_REVERSE
        ansi_codes, ansi_rev, hex_rev = ansi_color_code._codes = ANSI_COLORS, ANSI_COLORS_REVERSE, HEX_COLORS_REVERSE

    try:
        if color.isdigit():
            color = ansi_rev[color]
            return code + ansi_codes[color] + 'm'
        elif color.startswith('#'):
            return code + hex_rev[color.lower()] + 'm'
        else:
            return code + ansi_codes[color] + 'm'
    except KeyError as e:
        raise InvalidAnsiCode(color) from e


class InvalidAnsiCode(ValueError):
    """Exception to be raised when an invalid ANSI color/attribute code is selected"""
