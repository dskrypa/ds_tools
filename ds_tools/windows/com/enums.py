from enum import Enum, EnumMeta

__all__ = ['ComClassEnum']

_NotSet = object()


class ExtendedEnumMeta(EnumMeta):
    """Extends EnumMeta to allow ComClassEnum subclasses to register themselves by container class"""
    _clsids = {}

    # noinspection PyMethodOverriding
    @classmethod
    def __prepare__(mcs, cls, bases, parent=None, attr=None):
        return super().__prepare__(cls, bases)

    def __new__(mcs, cls, bases, classdict, parent=None, attr=None):
        _class = super().__new__(mcs, cls, bases, classdict)
        if cls != 'ComClassEnum':
            if parent is None:
                raise TypeError('__new__() missing 1 required argument: \'parent\'')
            elif attr is None:
                raise TypeError('__new__() missing 1 required argument: \'attr\'')
            ExtendedEnumMeta._clsids[str(parent.CLSID)] = _class
            _class._attr = attr
        return _class


class ComClassEnum(Enum, metaclass=ExtendedEnumMeta):
    @property
    def value(self):
        return self._value_[0]

    @property
    def cls(self):
        return self._value_[1]

    @classmethod
    def get_child_class(cls, clsid):
        return cls._clsids.get(str(clsid))

    @classmethod
    def for_num(cls, num: int, default=_NotSet):
        for value in cls:
            if value.value == num:
                return value
        if default is _NotSet:
            raise ValueError(f'No {cls.__name__} found with value={num}')
        return default
