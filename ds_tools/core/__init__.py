"""
Core utilities that are used by multiple other modules/packages in ds_tools.

:author: Doug Skrypa
"""

from importlib import import_module

__attr_module_map = {'wrap_main': 'main'}

# noinspection PyUnresolvedReferences
__all__ = ['collections', 'decorate', 'introspection', 'itertools', 'main', 'patterns', 'serialization', 'sql']
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
