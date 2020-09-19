"""
Core utilities that are used by multiple other modules/packages in ds_tools.

:author: Doug Skrypa
"""

from importlib import import_module

__attr_module_map = {
    # decorate
    'cached_property_or_err': 'decorate',
    'classproperty': 'decorate',
    'partitioned_exec': 'decorate',
    'rate_limited': 'decorate',
    'timed': 'decorate',
    'trace_entry': 'decorate',
    'trace_exit': 'decorate',
    'trace_entry_and_dump_stack': 'decorate',
    'wrap_main': 'decorate',
    'primed_coroutine': 'decorate',
    'basic_coroutine': 'decorate',
    'trace_entry_and_exit': 'decorate',
    # itertools
    'chunked': 'itertools',
    'flatten_mapping': 'itertools',
    'itemfinder': 'itertools',
    'kwmerge': 'itertools',
    'merge': 'itertools',
    'partitioned': 'itertools',
    # patterns
    'fnmatches': 'patterns',
    'any_fnmatches': 'patterns',
    'FnMatcher': 'patterns',
    'ReMatcher': 'patterns',
}

# noinspection PyUnresolvedReferences
__all__ = ['collections', 'decorate', 'introspection', 'itertools', 'patterns', 'serialization', 'sql']
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
