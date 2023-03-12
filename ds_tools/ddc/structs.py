"""
Structs for VCP

:author: Doug Skrypa
"""

from __future__ import annotations

from ctypes import Structure, sizeof, byref, c_char
from enum import IntFlag
from functools import cached_property
from typing import TYPE_CHECKING

try:
    from ctypes import WinError, windll
    from ctypes.wintypes import DWORD, HANDLE, WCHAR, RECT, HMONITOR
except ImportError:  # Not on Windows
    DWORD = HANDLE = WCHAR = RECT = HMONITOR = windll = WinError = dxva2 = user32 = None
else:
    dxva2, user32 = windll.dxva2, windll.user32

from .exceptions import VCPError

if TYPE_CHECKING:
    from ._windows import Adapter

__all__ = ['PhysicalMonitor', 'MC_VCP_CODE_TYPE', 'DisplayDevice', 'AdapterState', 'MonitorState', 'MonitorInfo']


class PhysicalMonitor(Structure):
    _fields_ = [('handle', HANDLE), ('description', WCHAR * 128)]
    handle: HANDLE
    description: str

    @classmethod
    def count(cls, handle: HMONITOR) -> int:
        num_physical = DWORD()
        try:
            if not dxva2.GetNumberOfPhysicalMonitorsFromHMONITOR(handle, byref(num_physical)):
                raise WinError()
        except OSError as e:
            raise VCPError('Windows API call failed') from e

        if (count := num_physical.value) != 1:
            # The Windows API does not allow opening and closing of individual physical monitors without their handles
            raise VCPError(f'Found unexpected {count=} physical monitors for hmonitor={handle}')
        return count

    @classmethod
    def for_handle(cls, handle: HMONITOR) -> PhysicalMonitor:
        count = cls.count(handle)
        physical_monitors = (PhysicalMonitor * count)()
        try:
            if not dxva2.GetPhysicalMonitorsFromHMONITOR(handle, count, physical_monitors):
                raise WinError()
        except OSError as e:
            raise VCPError('Failed to open physical monitor handle') from e
        return physical_monitors[0]  # There is only ever one item in the list due to the count == 1 check

    def __repr__(self) -> str:
        handle, description = self.handle, self.description
        return f'<{self.__class__.__name__}[{handle=}, {description=}]>'

    def get_capabilities(self) -> str:
        cap_len = DWORD()
        if not dxva2.GetCapabilitiesStringLength(self.handle, byref(cap_len)):
            raise WinError()

        caps_string = (c_char * cap_len.value)()
        if not dxva2.CapabilitiesRequestAndCapabilitiesReply(self.handle, caps_string, cap_len):
            raise WinError()

        return caps_string.value.decode('ASCII')

    def save_settings(self):
        if not dxva2.SaveCurrentMonitorSettings(self.handle):
            raise WinError()

    def close(self):
        try:
            dxva2.DestroyPhysicalMonitor(self.handle)
        except OSError as e:
            raise VCPError('Failed to close handle') from e


class MC_VCP_CODE_TYPE(Structure):
    _fields_ = [('MC_MOMENTARY', DWORD), ('MC_SET_PARAMETER', DWORD)]


class DisplayDevice(Structure):
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
    name: str           # Follows this format: \\\\.\\DISPLAY##\\Monitor0
    description: str    # Description that includes brand or model and a brief summary of connector (HDMI / DP / etc)
    state_flags: int    # Bit-packed flags for AdapterState / MonitorState
    id: str             # Includes something related to device model, and a guid
    key: str            # Path to the registry key related to this device

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._struct_size = sizeof(self)
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


class MonitorInfo(Structure):
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
        self._struct_size = sizeof(self)
        self.flags = 0x01  # MONITORINFOF_PRIMARY

    @classmethod
    def for_handle(cls, handle: HMONITOR) -> MonitorInfo:
        self = cls()
        if not user32.GetMonitorInfoW(handle, byref(self)):
            raise WinError()
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
