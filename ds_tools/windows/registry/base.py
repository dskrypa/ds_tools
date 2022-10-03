from __future__ import annotations

import logging
import winreg
from functools import cached_property
from itertools import count
from winreg import KEY_READ, OpenKey, EnumValue, EnumKey, HKEYType, QueryValueEx, QueryValue
from typing import Union, Optional, Iterator, Callable, TypeVar, Type, Generic, Any

from .enums import HKEYSection, RegType

__all__ = ['Attribute', 'Key', 'NamedAttribute']
log = logging.getLogger(__name__)

HKEY_KV_MAP: dict[str, int] = {k: getattr(winreg, k) for k in dir(winreg) if k.startswith('HKEY_')}
HKEY_VK_MAP: dict[int, str] = {v: k for k, v in HKEY_KV_MAP.items()}

AT = TypeVar('AT')
T = TypeVar('T')
ValAndType = tuple[Any, Optional[int]]


class NodeError(Exception):
    pass


class Attribute(Generic[T]):
    __slots__ = ('name', 'value', 'type')

    def __init__(self, name: str, value: T, type: int):  # noqa
        self.name = name
        self.value = value
        self.type = type
        log.debug(f'Initialized {self}')

    def __repr__(self) -> str:
        return f'Attribute({self.name!r}, {self.value!r}, {self.type!r})'

    @classmethod
    def from_key(cls, key: HKEYType, index: int) -> Attribute:
        return cls(*EnumValue(key, index))


class Key:
    def __init__(self, base_key: int, path: str):
        self.base_key = base_key
        self.path = path
        self.name = path.rsplit('\\', 1)[1]
        log.debug(f'Initialized {self}')

    @property
    def full_path(self) -> str:
        return f'{self.base_key_name}\\{self.path}'

    @property
    def base_key_name(self) -> str:
        return HKEY_VK_MAP[self.base_key]

    def __repr__(self) -> str:
        return f'<{self.__class__.__name__}({self.base_key_name}, {self.path!r})>'

    def open(self, reserved: int = 0, access: int = KEY_READ) -> HKEYType:
        return OpenKey(self.base_key, self.path, reserved, access)

    def enumerate(self, func: Callable[[HKEYType, int], T]) -> Iterator[T]:
        with self.open() as key:
            for n in count():
                try:
                    yield func(key, n)
                except OSError:
                    break

    @cached_property
    def key_names(self) -> tuple[str]:
        return tuple(self.enumerate(EnumKey))

    @cached_property
    def keys(self) -> dict[str, Key]:
        return {name: Key(self.base_key, f'{self.path}\\{name}') for name in self.key_names}

    @cached_property
    def attrs(self) -> dict[str, Attribute]:
        log.debug(f'Processing attributes for {self}')
        return {name: Attribute(name, value, attr_type) for name, value, attr_type in self.enumerate(EnumValue)}

    def as_dict(self, root: bool = True, recursive: bool = True):
        if recursive:
            keys = {key: val.as_dict(False, True) for key, val in self.keys.items()}
        else:
            keys = {key: ... for key in self.key_names}

        return {
            'name': self.full_path if root else self.name,
            'attrs': {key: attr.value for key, attr in self.attrs.items()},
            'keys': keys,
        }


class NamedAttribute:
    __slots__ = ('name', 'key', 'type')

    def __init__(self, name: str, key: str = None, type: Optional[Callable[[T], AT]] = None):  # noqa
        self.name = name
        self.key = key
        self.type = type

    def __get__(self, instance: Optional[Key], owner: Type[Key]) -> Union[NamedAttribute, T, AT]:
        if instance is None:
            return self
        if key := self.key:
            instance = instance.keys[key]
        value = instance.attrs[self.name].value
        if (type_func := self.type) is not None:
            return type_func(value)
        return value


class Node:
    def __init__(self, section: Union[str, int, HKEYSection], path: str, val_and_type: ValAndType = None):
        self.section = HKEYSection(section)
        self.path = path
        self.name = path.rsplit('\\', 1)[1]
        self._val_and_type = val_and_type
        # log.debug(f'Initialized {self}')

    @property
    def full_path(self) -> str:
        return f'{self.section_name}\\{self.path}'

    @property
    def section_name(self) -> str:
        return self.section.name

    def __repr__(self) -> str:
        return f'<{self.__class__.__name__}({self.section_name}, {self.path!r}, {self.value!r}, {self.type!r})>'

    def open(self, reserved: int = 0, access: int = KEY_READ) -> HKEYType:
        try:
            return OpenKey(self.section, self.path, reserved, access)
        except FileNotFoundError as e:
            raise NodeError(f'Node does not exist: {self.full_path}') from e

    def open_parent(self, reserved: int = 0, access: int = KEY_READ) -> HKEYType:
        path = self.path.rsplit('\\', 1)[0]
        try:
            return OpenKey(self.section, path, reserved, access)
        except FileNotFoundError as e:
            raise NodeError(f'Node does not exist: {self.section_name}\\{path}') from e

    @cached_property
    def _value_and_type(self) -> tuple[Any, Optional[int]]:
        if self._val_and_type is None:
            with self.open_parent() as key:
                try:
                    return QueryValueEx(key, self.name)
                except OSError:
                    return None, None
        return self._val_and_type

    @property
    def value(self) -> Any:
        return self._value_and_type[0]

    @property
    def type(self) -> Optional[RegType]:
        if (reg_type := self._value_and_type[1]) is not None:
            return RegType(reg_type)
        return reg_type

    def enumerate(self, func: Callable[[HKEYType, int], T]) -> Iterator[T]:
        with self.open() as key:
            for n in count():
                try:
                    yield func(key, n)
                except OSError:
                    break

    @cached_property
    def children(self) -> dict[str, Node]:
        return self._nodes | self._attrs

    @cached_property
    def _key_names(self) -> tuple[str]:
        return tuple(self.enumerate(EnumKey))

    @cached_property
    def _nodes(self) -> dict[str, Node]:
        try:
            return {name: Node(self.section, f'{self.path}\\{name}') for name in self._key_names}
        except NodeError:
            return {}

    @cached_property
    def _attrs(self) -> dict[str, Node]:
        try:
            return {n: Node(self.section, f'{self.path}\\{n}', (v, t)) for n, v, t in self.enumerate(EnumValue)}
        except NodeError:
            return {}

    def serializable(self, basic: bool = True):
        if basic:
            return self._serializable_basic()
        return self._serializable_full(basic)

    def _serializable_full(self, basic: bool):
        try:
            reg_type = self.type.name
        except AttributeError:
            reg_type = None

        return {
            'type': reg_type,
            'value': self.value,
            'children': {key: val.serializable(basic) for key, val in sorted(self.children.items())},
        }

    def _serializable_basic(self):
        if self.type is not None and not self.children:
            return self.value
        if self.type is None and self.children:
            return {key: val._serializable_basic() for key, val in sorted(self.children.items())}
        return self._serializable_full(True)

    def as_dict(self, recursive: bool = True, children: bool = True):
        try:
            reg_type = self.type.name
        except AttributeError:
            reg_type = None
        data = {'type': reg_type, 'value': self.value}
        if not children:
            return data

        if not recursive:
            children = False
        data['children'] = {key: val.as_dict(recursive, children) for key, val in sorted(self.children.items())}
        return data


class NodeAttribute:
    __slots__ = ('name', 'key', 'type')

    def __init__(self, name: str, key: str = None, type: Optional[Callable[[T], AT]] = None):  # noqa
        self.name = name
        self.key = key
        self.type = type

    def __get__(self, instance: Optional[Node], owner: Type[Node]) -> Union[NodeAttribute, T, AT]:
        if instance is None:
            return self
        if key := self.key:
            instance = instance.children[key]
        value = instance.children[self.name].value
        if (type_func := self.type) is not None:
            return type_func(value)
        return value
