"""
Output formatting package.

:author: Doug Skrypa
"""

from importlib import import_module

__attr_module_map = {
    # color
    'colored': 'color',
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
