"""
Output formatting package.

:author: Doug Skrypa
"""

from importlib import import_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .color import colored
    from .constants import PRINTER_FORMATS
    from .formatting import readable_bytes, short_repr, bullet_list
    from .printer import Printer
    from .table import Column, SimpleColumn, Table, TableBar, HeaderRow
    from .terminal import uprint, uerror

__attr_module_map = {
    # color
    'colored': 'color',
    # constants
    'PRINTER_FORMATS': 'constants',
    # formatting
    'readable_bytes': 'formatting',
    'short_repr': 'formatting',
    'bullet_list': 'formatting',
    # printer
    'Printer': 'printer',
    # table
    'Column': 'table',
    'SimpleColumn': 'table',
    'Table': 'table',
    'TableBar': 'table',
    'HeaderRow': 'table',
    # terminal
    'uprint': 'terminal',
    'uerror': 'terminal',
}

# noinspection PyUnresolvedReferences
__all__ = ['color', 'formatting', 'printer', 'table', 'terminal']
__all__.extend(__attr_module_map.keys())


def __dir__():
    return sorted(__all__ + list(globals().keys()))


def __getattr__(name):
    try:
        module_name = __attr_module_map[name]
    except KeyError:
        raise AttributeError(f'module {__name__!r} has no attribute {name!r}')
    else:
        module = import_module(f'.{module_name}', __name__)
        return getattr(module, name)
