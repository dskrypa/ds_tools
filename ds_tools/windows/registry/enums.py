from __future__ import annotations

import winreg
from enum import IntEnum
from typing import Union

__all__ = ['DeviceState', 'HKEYSection', 'RegType']


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


class HKEYSection(IntEnum):
    HKEY_CLASSES_ROOT = winreg.HKEY_CLASSES_ROOT
    HKEY_CURRENT_CONFIG = winreg.HKEY_CURRENT_CONFIG
    HKEY_CURRENT_USER = winreg.HKEY_CURRENT_USER
    HKEY_DYN_DATA = winreg.HKEY_DYN_DATA
    HKEY_LOCAL_MACHINE = winreg.HKEY_LOCAL_MACHINE
    HKEY_PERFORMANCE_DATA = winreg.HKEY_PERFORMANCE_DATA
    HKEY_USERS = winreg.HKEY_USERS

    @classmethod
    def _missing_(cls, value: str):
        if isinstance(value, str):
            value = value.upper()
            for member_map in (cls._member_map_, HKEY_SECTION_ALIASES):
                try:
                    return member_map[value]
                except KeyError:
                    pass
        return super()._missing_(value)


HKEY_SECTION_ALIASES = {
    'HKCR': HKEYSection.HKEY_CLASSES_ROOT,
    'HKCC': HKEYSection.HKEY_CURRENT_CONFIG,
    'HKCU': HKEYSection.HKEY_CURRENT_USER,
    'HKDD': HKEYSection.HKEY_DYN_DATA,
    'HKLM': HKEYSection.HKEY_LOCAL_MACHINE,
    'HKPD': HKEYSection.HKEY_PERFORMANCE_DATA,
    'HKU': HKEYSection.HKEY_USERS,
}


class RegType(IntEnum):
    REG_BINARY = winreg.REG_BINARY                                          # Binary data in any form
    REG_DWORD = winreg.REG_DWORD                                            # A 32-bit number
    REG_DWORD_BIG_ENDIAN = winreg.REG_DWORD_BIG_ENDIAN                      # A 32-bit BE number
    REG_DWORD_LITTLE_ENDIAN = winreg.REG_DWORD_LITTLE_ENDIAN                # A 32-bit LE number (equiv. to DWORD)
    REG_EXPAND_SZ = winreg.REG_EXPAND_SZ                                    # SZ containing env var refs
    REG_FULL_RESOURCE_DESCRIPTOR = winreg.REG_FULL_RESOURCE_DESCRIPTOR      # A hardware setting
    REG_LINK = winreg.REG_LINK                                              # A unicode symbolic link
    REG_MULTI_SZ = winreg.REG_MULTI_SZ                                      # Sequence of SZs, ending in 2 null chars
    REG_NONE = winreg.REG_NONE                                              # No defined value type
    REG_QWORD = winreg.REG_QWORD                                            # A 64-bit number
    REG_QWORD_LITTLE_ENDIAN = winreg.REG_QWORD_LITTLE_ENDIAN                # A 64-bit LE number (equiv. to REG_QWORD)
    REG_RESOURCE_LIST = winreg.REG_RESOURCE_LIST                            # A device driver resource list
    REG_RESOURCE_REQUIREMENTS_LIST = winreg.REG_RESOURCE_REQUIREMENTS_LIST  # A hardware resource list
    REG_SZ = winreg.REG_SZ                                                  # A null-terminated string

    @classmethod
    def _missing_(cls, value: str):
        if isinstance(value, str):
            value = value.upper()
            if not value.startswith('REG_'):
                value = f'REG_{value}'
            try:
                return cls._member_map_[value]
            except KeyError:
                pass
        return super()._missing_(value)
