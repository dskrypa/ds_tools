"""
Mixins

:author: Doug Skrypa
"""

from abc import ABC
from functools import cached_property

__all__ = ['ClearableCachedPropertyMixin', 'DictAttrProperty', 'DictAttrFieldNotFoundError', 'ClearableCachedProperty']
_NotSet = object()


class ClearableCachedProperty(ABC):
    _set_name = False

    def __set_name__(self, owner, name):
        if self._set_name:
            self.name = name


# noinspection PyUnresolvedReferences
ClearableCachedProperty.register(cached_property)


class ClearableCachedPropertyMixin:
    @classmethod
    def _cached_properties(cls):
        cached_properties = {}
        for clz in cls.mro():
            if clz == cls:
                for k, v in cls.__dict__.items():
                    if isinstance(v, ClearableCachedProperty):
                        cached_properties[k] = v
            else:
                try:
                    # noinspection PyUnresolvedReferences
                    cached_properties.update(clz._cached_properties())
                except AttributeError:
                    pass
        return cached_properties

    def clear_cached_properties(self):
        for prop in self._cached_properties():
            try:
                del self.__dict__[prop]
            except KeyError:
                pass


class DictAttrProperty(ClearableCachedProperty):
    def __init__(self, attr, path, type=_NotSet, default=_NotSet, default_factory=_NotSet, delim='.'):
        """
        Descriptor that acts as a cached property for retrieving values nested in a dict stored in an attribute of the
        object that this :class:`DictAttrProperty` is a member of.  The value is not accessed or stored until the first
        time that it is accessed.

        As an instance attribute of a subclass of :class:`DictAttrPropertyMixin` (or any class that has
        :class:`DictAttrPropertyMeta` as its metaclass), replaces itself with the value found at the given key in that
        instance's provided attribute.  Without :class:`DictAttrPropertyMeta` as its metaclass, the value is re-computed
        each time it is accessed.

        To un-cache a value (causes the descriptor to take over again)::\n
            >>> del instance.__dict__[attr_name]

        The :class:`ClearableCachedPropertyMixin` mixin class can be used to facilitate clearing all
        :class:`DictAttrProperty` and any similar cached properties that exist in a given object.

        :param str attr: Name of the attribute in the class that this DictAttrProperty is in that contains the dict that
          This DictAttrProperty should reference
        :param str path: The nexted key location in the dict attribute of the value that this DictAttrProperty
          represents; dict keys should be separated by ``.``, otherwise the delimiter should be provided via ``delim``
        :param callable type: Callable that accepts 1 argument; the value of this DictAttrProperty will be passed to it,
          and the result will be returned as this DictAttrProperty's value (default: no conversion)
        :param default: Default value to return if a KeyError is encountered while accessing the given path
        :param callable default_factory: Callable that accepts no arguments to be used to generate default values
          instead of an explicit default value
        :param str delim: Separator that was used between keys in the provided path (default: ``.``)
        """
        self.path = [p for p in path.split(delim) if p]
        self.path_repr = delim.join(self.path)
        self.attr = attr
        self.type = type
        self.name = '_{}#{}'.format(self.__class__.__name__, self.path_repr)
        self.default = default
        self.default_factory = default_factory

    def __set_name__(self, owner, name):
        self.name = name
        self.__doc__ = """
        A :class:`DictAttrProperty<ds_tools.caching.mixins.DictAttrProperty>` that references this {}
        instance's {}{}""".format(owner.__name__, self.attr, ''.join('[{!r}]'.format(p) for p in self.path))

    def __get__(self, obj, cls):
        if obj is None:
            return self

        value = getattr(obj, self.attr)
        for key in self.path:
            try:
                value = value[key]
            except KeyError:
                if self.default is not _NotSet:
                    value = self.default
                    break
                elif self.default_factory is not _NotSet:
                    value = self.default_factory()
                    break
                raise DictAttrFieldNotFoundError(obj, self.name, self.attr, self.path_repr)

        if self.type is not _NotSet:
            # noinspection PyArgumentList
            value = self.type(value)
        if '#' not in self.name:
            obj.__dict__[self.name] = value
        return value


class DictAttrFieldNotFoundError(Exception):
    def __init__(self, obj, prop_name, attr, path_repr):
        self.obj = obj
        self.prop_name = prop_name
        self.attr = attr
        self.path_repr = path_repr

    def __str__(self):
        fmt = '{!r} object has no attribute {!r} ({} not found in {!r}.{})'
        return fmt.format(type(self.obj).__name__, self.prop_name, self.path_repr, self.obj, self.attr)
