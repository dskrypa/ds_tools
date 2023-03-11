"""
Structs for VCP

:author: Doug Skrypa
"""

from __future__ import annotations

import ctypes
import sys
from enum import IntFlag
from functools import cached_property
from typing import TYPE_CHECKING

if sys.platform == 'win32':
    from ctypes.wintypes import DWORD, HANDLE, WCHAR, RECT
else:
    DWORD = HANDLE = WCHAR = RECT = None

if TYPE_CHECKING:
    from ._windows import Adapter

__all__ = ['PhysicalMonitor', 'MC_VCP_CODE_TYPE', 'DisplayDevice', 'AdapterState', 'MonitorState', 'MonitorInfo']


class PhysicalMonitor(ctypes.Structure):
    _fields_ = [('handle', HANDLE), ('description', WCHAR * 128)]
    handle: HANDLE
    description: str


class MC_VCP_CODE_TYPE(ctypes.Structure):
    _fields_ = [('MC_MOMENTARY', DWORD), ('MC_SET_PARAMETER', DWORD)]


class DisplayDevice(ctypes.Structure):
    # Info source: https://docs.microsoft.com/en-us/windows/win32/api/wingdi/ns-wingdi-display_devicea
    adapter: Adapter | None
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
        self.adapter = None

    def __repr__(self) -> str:
        name, description, state, key = self.name, self.description, self.state, self.key
        return f'<DisplayDevice[type={self.type}, {name=}, {description=}, {state=}, id={self.id!r}, {key=}]>'

    @cached_property
    def type(self) -> str:
        return 'monitor' if self.id.startswith('MONITOR\\') else 'adapter'

    @cached_property
    def state(self) -> AdapterState | MonitorState:
        return AdapterState(self.state_flags) if self.type == 'adapter' else MonitorState(self.state_flags)


class MonitorInfo(ctypes.Structure):
    """Technically a MONITORINFOEX structure due to the inclusion of the ``name`` field."""
    # Info source: https://docs.microsoft.com/en-us/windows/win32/api/winuser/ns-winuser-monitorinfo
    _fields_ = [
        ('_struct_size', DWORD), ('monitor_rect', RECT), ('work_area', RECT), ('flags', DWORD), ('name', WCHAR * 32)
    ]
    # Note: RECT has attrs: top, bottom, left, right
    monitor_rect: RECT  # Virtual screen coordinates that specify the bounding box for this monitor
    work_area: RECT     # Portion of screen not obscured by the taskbar / app desktop toolbars (virt screen coordinates)
    flags: int
    name: str

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._struct_size = ctypes.sizeof(self)
        self.flags = 0x01  # MONITORINFOF_PRIMARY

    @classmethod
    def for_handle(cls, handle) -> MonitorInfo:
        self = cls()
        if not ctypes.windll.user32.GetMonitorInfoW(handle, ctypes.byref(self)):
            raise ctypes.WinError()
        return self

    def __repr__(self) -> str:
        rect, work_area, flags, name = self.monitor_rect, self.work_area, self.flags, self.name
        return f'<MonitorInfo[{name=}, {rect=}, {work_area=}, {flags=}]>'


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
