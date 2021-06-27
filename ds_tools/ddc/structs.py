"""
Structs for VCP

:author: Doug Skrypa
"""

import ctypes
import sys
from enum import IntFlag
from functools import cached_property

if sys.platform == 'win32':
    from ctypes.wintypes import DWORD, HANDLE, WCHAR
else:
    DWORD, HANDLE, WCHAR = None, None, None

__all__ = ['PhysicalMonitor', 'MC_VCP_CODE_TYPE', 'DisplayDevice', 'AdapterState', 'MonitorState']


class PhysicalMonitor(ctypes.Structure):
    _fields_ = [('handle', HANDLE), ('description', WCHAR * 128)]


class MC_VCP_CODE_TYPE(ctypes.Structure):
    _fields_ = [('MC_MOMENTARY', DWORD), ('MC_SET_PARAMETER', DWORD)]


class DisplayDevice(ctypes.Structure):
    # Info source: https://docs.microsoft.com/en-us/windows/win32/api/wingdi/ns-wingdi-display_devicea
    _fields_ = [
        ('_struct_size', DWORD),
        ('name', WCHAR * 32),
        ('description', WCHAR * 128),
        ('state_flags', DWORD),
        ('id', WCHAR * 128),
        ('key', WCHAR * 128),
    ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._struct_size = ctypes.sizeof(self)

    def __repr__(self):
        return (
            f'<DisplayDevice[type={self.type} name={self.name!r} description={self.description!r} state={self.state!r}'
            f' id={self.id!r} key={self.key!r}]>'
        )

    @cached_property
    def type(self) -> str:
        return 'monitor' if self.id.startswith('MONITOR\\') else 'adapter'

    @cached_property
    def state(self):
        return AdapterState(self.state_flags) if self.type == 'adapter' else MonitorState(self.state_flags)


class AdapterState(IntFlag):
    # Based on https://github.com/wine-mirror/wine/blob/542175ab10420953920779f3c64eb310dd3aa258/include/wingdi.h#L3331
    ATTACHED = 1
    MULTI_DRIVER = 2
    PRIMARY = 4
    MIRRORING_DRIVER = 8
    VGA_COMPATIBLE = 16
    REMOVABLE = 32
    # MODES_PRUNED = ??


class MonitorState(IntFlag):
    ACTIVE = 1
    ATTACHED = 2
