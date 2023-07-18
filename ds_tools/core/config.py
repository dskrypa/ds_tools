"""
This module provides a base class for configuration classes, and the ConfigItem descriptor that is intended to be used
to define each configurable option in subclasses of ConfigSection.
"""

from __future__ import annotations

from collections import ChainMap
from typing import Union, TypeVar, Callable, Iterable, Any, Mapping, Generic, Type, overload

__all__ = [
    'ConfigItem', 'NestedSection', 'ConfigSection', 'ConfigException', 'InvalidConfigError', 'MissingConfigItemError'
]

CV = TypeVar('CV')
DV = TypeVar('DV')
ConfigValue = Union[CV, DV]

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
    _nested_config_sections_: dict[str, NestedSection]

    @classmethod
    def __prepare__(mcs, name: str, bases: Iterable[type], **kwargs) -> dict[str, Any]:
        """Called before ``__new__`` and before evaluating the contents of a class."""
        config_items, nested_sections = {}, {}
        for base in bases:
            if isinstance(base, mcs):
                config_items.update(base._config_items_)
                nested_sections.update(base._nested_config_sections_)
        return {'_config_items_': config_items, '_nested_config_sections_': nested_sections}


class ConfigSection(metaclass=ConfigMeta):
    _config_items_: dict[str, ConfigItem | NestedSection]
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

    def __init__(self, config: Mapping[str, Any] = None, **kwargs):
        if data := ChainMap(config, kwargs) if config and kwargs else (config or kwargs):
            if self._strict_config_keys_ and (bad := set(data).difference(self._config_items_)):
                raise InvalidConfigError(f'Invalid configuration - unsupported options: {", ".join(sorted(bad))}')

            for key, val in data.items():
                setattr(self, key, val)

    def _update_(self, config: Mapping[str, Any] = None, **kwargs):
        if data := ChainMap(config, kwargs) if config and kwargs else (config or kwargs):
            if self._strict_config_keys_ and (bad := set(data).difference(self._config_items_)):
                raise InvalidConfigError(f'Invalid configuration - unsupported options: {", ".join(sorted(bad))}')
            elif self._merge_nested_sections_:
                for key, val in data.items():
                    if key in self._nested_config_sections_:  # Merge nested configs instead of overwriting them
                        getattr(self, key)._update_(val)
                    else:
                        setattr(self, key, val)
            else:
                for key, val in data.items():
                    setattr(self, key, val)

    update = _update_

    def __contains__(self, key: str) -> bool:
        """
        Returns True if the given key is a config item in this section (or a subsection thereof, if a delimiter
        was configured and was present in the key), and it has a non-default value.  If the key is a config item that
        only has a default value, then False will be returned instead.  False will always be returned for keys that are
        not associated with any config items.
        """
        if self._config_key_delimiter_:
            base, _, remainder = key.partition(self._config_key_delimiter_)
        else:
            base, remainder = key, ''

        if base not in self._config_items_:
            return False
        elif not remainder:
            return base in self.__dict__  # A non-default value exists for the given key
        else:
            return remainder in getattr(self, base)

    def __getitem__(self, key: str):
        if self._config_key_delimiter_:
            base, _, remainder = key.partition(self._config_key_delimiter_)
        else:
            base, remainder = key, ''

        if base not in self._config_items_:
            raise KeyError(key)
        elif remainder:
            return getattr(self, base)[remainder]
        else:
            return getattr(self, base)

    def __setitem__(self, key: str, value: Any):
        if self._config_key_delimiter_:
            base, _, remainder = key.partition(self._config_key_delimiter_)
        else:
            base, remainder = key, ''

        if self._strict_config_keys_ and base not in self._config_items_:
            raise KeyError(key)
        elif remainder:
            getattr(self, base)[remainder] = value
        else:
            setattr(self, base, value)

    def __delitem__(self, key: str):
        if self._config_key_delimiter_:
            base, _, remainder = key.partition(self._config_key_delimiter_)
        else:
            base, remainder = key, ''

        if self._strict_config_keys_ and base not in self._config_items_:
            raise KeyError(key)
        elif remainder:
            del getattr(self, base)[remainder]
        else:
            delattr(self, base)


# TODO: Config subclass of ConfigSection, with from_json_file and similar classmethods?


# region Exceptions


class ConfigException(Exception):
    """Base exception for config-related errors"""


class InvalidConfigError(ConfigException):
    """Raised when invalid config items are provided when initializing a ConfigSection"""


class MissingConfigItemError(ConfigException):
    """Raised if a required config item is accessed when no value was provided for it"""


# endregion
