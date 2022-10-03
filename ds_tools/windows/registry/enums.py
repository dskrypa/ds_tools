from __future__ import annotations

from enum import IntEnum
from typing import Union

__all__ = ['DeviceState']


class DeviceState(IntEnum):
    # https://learn.microsoft.com/en-us/windows/win32/coreaudio/device-state-xxx-constants?redirectedfrom=MSDN
    ACTIVE = 1
    DISABLED = 2
    NOT_PRESENT = 4
    UNPLUGGED = 8

    @classmethod
    def _missing_(cls, value: Union[str, int]):
        if isinstance(value, int) and value & 0x0f:
            for member in cls:
                if value & member:
                    return member
        elif isinstance(value, str):
            try:
                return cls._member_map_[value.upper()]
            except KeyError:
                pass
        return super()._missing_(value)
