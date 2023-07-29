"""
This module provides a recipe for building classes to keep track of configuration info, and to perform basic
validation / normalization of config values.

The :class:`ConfigSection` class is intended to be used as a base class for configuration classes, and the
:class:`ConfigItem` descriptor is intended to be used to define each configurable option in subclasses of ConfigSection.
"""

from __future__ import annotations

from collections import ChainMap
from typing import Union, TypeVar, Callable, Iterable, Any, Mapping, Generic, Type, Collection, overload

__all__ = [
    'ConfigItem', 'NestedSection', 'ConfigSection', 'ConfigException', 'InvalidConfigError', 'MissingConfigItemError'
]

T = TypeVar('T')
CV = TypeVar('CV')
DV = TypeVar('DV')
ConfigValue = Union[CV, DV]
Kwargs = Union[Mapping[str, Any], None]
ConfigMap = Union[Mapping[str, Any], 'ConfigSection', None]
CS = Union['ConfigMeta', 'ConfigSection']
Strs = Collection[str]

_NotSet = object()


class ConfigItem(Generic[CV, DV]):
    __slots__ = ('name', 'type', 'default', 'default_func')

    def __init__(
        self, default: DV = _NotSet, type: Callable[..., CV] = None, default_func: Callable[[], DV] = None  # noqa
    ):  # noqa
        self.type = type
        self.default = default
        self.default_func = default_func

    def __set_name__(self, owner: Type[ConfigSection], name: str):
        self.name = name
        owner._config_items_[name] = self
        owner._config_item_keys_.add(name)

    @overload
    def __get__(self, instance: None, owner: Type[ConfigSection]) -> ConfigItem[CV, DV]:
        ...

    @overload
    def __get__(self, instance: ConfigSection, owner: Type[ConfigSection]) -> ConfigValue:
        ...

    def __get__(self, instance, owner):
        try:
            return instance.__dict__[self.name]
        except AttributeError:  # instance is None
            return self
        except KeyError as e:
            if self.default is not _NotSet:
                return self.default
            elif self.default_func is not None:
                instance.__dict__[self.name] = value = self.default_func()
                return value
            raise MissingConfigItemError(self.name) from e

    def __set__(self, instance: ConfigSection, value: ConfigValue):
        if self.type is not None:
            value = self.type(value)
        instance.__dict__[self.name] = value

    def __delete__(self, instance: ConfigSection):
        try:
            del instance.__dict__[self.name]
        except KeyError as e:
            raise AttributeError(f'No {self.name!r} config was stored for {instance}') from e

    def __repr__(self) -> str:
        return f'<{self.__class__.__name__}({self.default!r}, type={self.type!r})>'


class NestedSection(ConfigItem):
    __slots__ = ()

    def __init__(self, section_cls: Type[ConfigSection]):
        super().__init__(type=section_cls, default_func=section_cls)

    def __set_name__(self, owner: Type[ConfigSection], name: str):
        super().__set_name__(owner, name)
        owner._nested_config_sections_[name] = self


class ConfigMeta(type):
    """
    Metaclass for ConfigSections.  Necessary to initialize the ``_config_items_`` and ``_nested_config_sections_`` dicts
    for ConfigItem registration because the contents of a class is evaluated before ``__init_subclass__`` is called.
    """
    _config_items_: dict[str, ConfigItem | NestedSection]
    _config_item_keys_: set[str]
    _nested_config_sections_: dict[str, NestedSection]

    @classmethod
    def __prepare__(mcs, name: str, bases: Iterable[type], **kwargs) -> dict[str, Any]:
        """Called before ``__new__`` and before evaluating the contents of a class."""
        config_items, nested_sections = {}, {}
        for base in bases:
            if isinstance(base, mcs):
                config_items.update(base._config_items_)
                nested_sections.update(base._nested_config_sections_)
        return {
            '_config_items_': config_items,
            '_config_item_keys_': set(config_items),
            '_nested_config_sections_': nested_sections,
        }

    def filter(
        cls,
        *configs: Mapping[str, T],
        exclude: Strs = (),
        truthy: bool = False,
        unflatten: bool = False,
    ) -> dict[str, T]:
        if configs := [c for c in (c.__dict__ if isinstance(c, ConfigSection) else c for c in configs) if c]:
            config = ChainMap(*configs) if len(configs) > 1 else configs[0]
            config_map = _config_map(cls, config, check_keys=False)
            if unflatten:
                return _unflatten(cls, config_map, exclude, truthy)
            else:
                return _filter(cls, config_map, exclude, truthy)
        return {}


def _unflatten(
    section: CS, config: Mapping[str, T], exclude: Strs = (), truthy: bool = False, unflattened: dict[str, T] = None
) -> dict[str, T]:
    if unflattened is None:
        unflattened = _filter(section, config, exclude, truthy)
    else:
        unflattened |= _filter(section, config, exclude, truthy)

    for key, ns in section._nested_config_sections_.items():
        if key in exclude:
            continue

        nested_unflattened = unflattened.get(key)
        nested_section: Type[ConfigSection] = ns.type  # noqa
        nested = _unflatten(nested_section, config, exclude=exclude, truthy=truthy, unflattened=nested_unflattened)
        nested |= _filter(nested_section, config, exclude, truthy)
        if nested or nested_unflattened is not None:
            unflattened[key] = nested

    return unflattened


def _filter(section: CS, config: Mapping[str, T], exclude: Strs = (), truthy: bool = False) -> dict[str, T]:
    keys = section._config_item_keys_.intersection(config).difference(exclude)
    if truthy:
        return {key: val for key in keys if (val := config[key])}
    return {key: config[key] for key in keys}


def _config_map(
    section: CS, config: ConfigMap, kwargs: Kwargs = None, check_keys: bool = True, only_known: bool = False
):
    if isinstance(config, ConfigSection):
        config = config.__dict__

    if config_map := ChainMap(config, kwargs) if config and kwargs else (config or kwargs):
        if check_keys and section._strict_config_keys_ and (bad := set(config_map) - section._config_item_keys_):
            raise InvalidConfigError(f'Invalid configuration - unsupported options: {", ".join(sorted(bad))}')
        if only_known:
            return _filter(section, config_map)
    return config_map


class ConfigSection(metaclass=ConfigMeta):
    _config_items_: dict[str, ConfigItem | NestedSection]
    _config_item_keys_: set[str]
    _nested_config_sections_: dict[str, NestedSection]
    _config_key_delimiter_: str | None = None
    _merge_nested_sections_: bool = True
    _strict_config_keys_: bool = True

    def __init_subclass__(cls, merge_nested: bool = None, key_delimiter: str = _NotSet, strict: bool = None, **kwargs):
        """
        :param merge_nested: If True (default), when calling :meth:`._update_` / :meth:`.update`, if a value is
          provided for a nested section, then that nested section should be updated with the new value, otherwise any
          overrides in it should be replaced with the provided new value so any nested overrides that existed before
          whose keys are not present in the new value will be lost.
        :param key_delimiter: A delimiter for nested keys to allow direct access to multiple levels of nested items.
          If None or another non-truthy value, then all keys will be treated at face value.
        :param strict: Whether init and update methods should accept keys that do not match registered ConfigItems
          (default: True / strict).
        """
        super().__init_subclass__(**kwargs)
        if merge_nested is not None and merge_nested != cls._merge_nested_sections_:
            cls._merge_nested_sections_ = False
        if key_delimiter is not _NotSet and key_delimiter != cls._config_key_delimiter_:
            cls._config_key_delimiter_ = key_delimiter
        if strict is not None and strict != cls._strict_config_keys_:
            cls._strict_config_keys_ = strict

    def __init__(self, config: ConfigMap = None, **kwargs):
        self.__init(config, kwargs)

    def __init(self, config: ConfigMap, kwargs: Kwargs = None, only_known: bool = False, clear: bool = False):
        if clear:
            self.__dict__.clear()

        if config_map := _config_map(self, config, kwargs, check_keys=not only_known, only_known=only_known):
            for key, val in config_map.items():
                if only_known and key in self._nested_config_sections_:
                    # Note: `clear` will only ever be True here due to how this is called by update_known
                    getattr(self, key).__init(val, only_known=only_known, clear=clear)
                else:
                    setattr(self, key, val)

    # region Update

    def _update_(self, config: ConfigMap = None, **kwargs):
        """
        Update this section with the given content.  If this is a ``strict`` section and any of the provided keys are
        not expected, then an :class:`InvalidConfigError` will be raised.  If this section was configured to merge
        nested sections' values (the default behavior), then the values for any keys that correspond with nested
        sections will be merged with existing values for those nested sections, otherwise they will be replaced.

        :param config: A dict or other mapping containing values that should be used in this section
        :param kwargs: Additional keyword arguments for values that should be used in this section
        """
        self.__update(config, kwargs, check_keys=True, only_known=False)

    update = _update_

    def _update_known_(self, config: ConfigMap = None, **kwargs):
        """
        Update this section with the given content.  Regardless of whether this is a ``strict`` section, the provided
        keys will be filtered to only those that are expected in this section.  No exception will be raised for
        unexpected keys.

        If this section was configured to merge nested sections' values (the default behavior), then the values for any
        keys that correspond with nested sections will be merged with existing values for those nested sections using
        the same key filtering behavior.  If merging is disabled,

        :param config: A dict or other mapping containing values that should be used in this section
        :param kwargs: Additional keyword arguments for values that should be used in this section
        """
        self.__update(config, kwargs, check_keys=False, only_known=True)

    update_known = _update_known_

    def __update(self, config: ConfigMap, kwargs: Kwargs = None, check_keys: bool = True, only_known: bool = False):
        """Used by both :meth:`._update_` and :meth:`._update_known_` to update this section and any nested sections."""
        config_map = _config_map(self, config, kwargs, check_keys=check_keys, only_known=only_known)
        if not config_map:
            return
        elif only_known or self._merge_nested_sections_:
            keys = set(config_map)
            if nested_keys := keys.intersection(self._nested_config_sections_):
                if self._merge_nested_sections_:
                    for key in nested_keys:
                        getattr(self, key).__update(config_map[key], check_keys=check_keys, only_known=only_known)
                else:
                    for key in nested_keys:
                        getattr(self, key).__init(config_map[key], only_known=only_known, clear=True)
            if item_keys := keys - nested_keys:
                for key in item_keys:
                    setattr(self, key, config_map[key])
        else:
            for key, val in config_map.items():
                setattr(self, key, val)

    # endregion

    # region Container Dunder Methods

    def __contains__(self, key: str) -> bool:
        """
        Returns True if the given key is a config item in this section (or a subsection thereof, if a delimiter
        was configured and was present in the key), and it has a non-default value.

        If the key is a config item that only has a default value, then False will be returned instead.

        If the section was defined with ``strict=False``, and a value was stored for a non-``ConfigItem`` key, then
        True will be returned for that key.  When ``strict=True``, False will always be returned for keys that are not
        associated with any config items.
        """
        try:
            base, remainder = self.__split_key(key)
        except KeyError:
            return False

        if not remainder:
            return base in self.__dict__  # A non-default value exists for the given key
        else:
            try:
                return remainder in getattr(self, base)
            except (AttributeError, TypeError):
                return False

    def __getitem__(self, key: str):
        base, remainder = self.__split_key(key)
        if remainder:
            try:
                return getattr(self, base)[remainder]
            except TypeError:
                raise KeyError(key) from None
        else:
            try:
                return getattr(self, base)
            except AttributeError:
                raise KeyError(key) from None

    def __setitem__(self, key: str, value: Any):
        base, remainder = self.__split_key(key)
        if remainder:
            try:
                getattr(self, base)[remainder] = value
            except TypeError:
                raise KeyError(key) from None
        else:
            setattr(self, base, value)

    def __delitem__(self, key: str):
        base, remainder = self.__split_key(key)
        if remainder:
            try:
                del getattr(self, base)[remainder]
            except TypeError:
                raise KeyError(key) from None
        else:
            try:
                delattr(self, base)
            except AttributeError:
                raise KeyError(key) from None

    def __split_key(self, key: str) -> tuple[str, str]:
        if self._config_key_delimiter_:
            base, _, remainder = key.partition(self._config_key_delimiter_)
        else:
            base, remainder = key, ''

        if self._strict_config_keys_ and base not in self._config_items_:
            raise KeyError(key)
        return base, remainder

    # endregion

    def _as_dict_(self, recursive: bool = True, include_defaults: bool = True) -> dict[str, Any]:
        keys = self._config_item_keys_.union(self.__dict__) if include_defaults else set(self.__dict__)
        config_map = {}
        if not recursive:
            keys.difference_update(self._nested_config_sections_)
        elif nested_keys := keys.intersection(self._nested_config_sections_):
            keys -= nested_keys
            for key in nested_keys:
                config_map[key] = getattr(self, key)._as_dict_(recursive, include_defaults)

        for key in keys:
            config_map[key] = getattr(self, key)

        return config_map

    as_dict = _as_dict_


# region Exceptions


class ConfigException(Exception):
    """Base exception for config-related errors"""


class InvalidConfigError(ConfigException):
    """Raised when invalid config items are provided when initializing a ConfigSection"""


class MissingConfigItemError(ConfigException):
    """Raised if a required config item is accessed when no value was provided for it"""


# endregion
