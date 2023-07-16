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


# region Exceptions


class ConfigException(Exception):
    """Base exception for config-related errors"""


class InvalidConfigError(ConfigException):
    """Raised when invalid config items are provided when initializing a ConfigSection"""


class MissingConfigItemError(ConfigException):
    """Raised if a required config item is accessed when no value was provided for it"""


# endregion


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
        if (type_func := self.type) is not None:
            value = type_func(value)
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


class ConfigMeta(type):
    """
    Metaclass for ConfigSections.  Necessary to initialize the ``_config_items_`` dict for ConfigItem registration
    because the contents of a class is evaluated before ``__init_subclass__`` is called.
    """

    @classmethod
    def __prepare__(mcs, name: str, bases: Iterable[type], **kwargs) -> dict[str, Any]:
        """Called before ``__new__`` and before evaluating the contents of a class."""
        return {
            '_config_items_': {
                k: v for base in bases for k, v in base._config_items_.items() if isinstance(base, mcs)  # noqa
            }
        }


class ConfigSection(metaclass=ConfigMeta):
    _config_items_: dict[str, ConfigItem | NestedSection]

    def __init__(self, config: Mapping[str, Any] = None, **kwargs):
        if data := ChainMap(config, kwargs) if config and kwargs else (config or kwargs):
            if bad := set(data).difference(self._config_items_):
                raise InvalidConfigError(f'Invalid configuration - unsupported options: {", ".join(sorted(bad))}')

            for key, val in data.items():
                setattr(self, key, val)

# TODO: Config subclass of ConfigSection, with from_json_file and similar classmethods?
