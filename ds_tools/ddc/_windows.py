"""
Windows API for accessing / controlling a monitor's VCP (Virtual Control Panel).

Originally based on `monitorcontrol.vcp.vcp_windows <https://github.com/newAM/monitorcontrol>`_

Available functions:
https://docs.microsoft.com/en-us/windows/win32/monitor/monitor-configuration-functions
Funcs, structs, enums:
https://docs.microsoft.com/en-us/windows/win32/monitor/monitor-configuration-reference

Additional potentially interesting things that are potentially available via ctypes.windll.{dll_name} are listed in
_notes/{dll_name}.txt
"""

from __future__ import annotations

import logging
from ctypes import POINTER, c_bool, byref
from functools import cached_property
from typing import TYPE_CHECKING, Optional, Iterator
from weakref import finalize

try:
    from ctypes import WinError, WINFUNCTYPE, windll
    from ctypes.wintypes import DWORD, RECT, BOOL, HMONITOR, HDC, LPARAM, HANDLE, BYTE, LPRECT
except ImportError:  # Not on Windows
    WinError = WINFUNCTYPE = windll = dxva2 = user32 = None
    DWORD = RECT = BOOL = HMONITOR = HDC = LPARAM = HANDLE = BYTE = LPRECT = None
else:
    dxva2, user32 = windll.dxva2, windll.user32

from .exceptions import VCPError
from .structs import PhysicalMonitor, MC_VCP_CODE_TYPE, DisplayDevice, MonitorState, MonitorInfo
from .vcp import VCP

if TYPE_CHECKING:
    from .features import FeatureOrId

__all__ = ['WindowsVCP']
log = logging.getLogger(__name__)


class WindowsVCP(VCP, close_attr='_monitor'):
    """
    Windows API access to a monitor's virtual control panel.

    References: https://stackoverflow.com/questions/16588133/
    """
    _monitors = {}

    def __init__(self, n: int, handle: int, device: DisplayDevice):
        """
        :param handle: logical monitor handle
        """
        super().__init__(n)
        self._handle = handle
        self.device = device

    def __repr__(self) -> str:
        return f'<{self.__class__.__name__}[{self.n}][{self.description!r}, handle={self._handle}]>'

    @classmethod
    def for_id(cls, monitor_id: str) -> WindowsVCP:
        """
        Truncated :class:`DisplayDevice<ds_tools.ddc.structs.DisplayDevice>` reprs showing example ID values::
            <DisplayDevice[name='\\\\.\\DISPLAY1\\Monitor0' description='CRG9_C49RG9xSS (DP)' id='MONITOR\\SAM0F9C\\{4d36e96e-e325-11ce-bfc1-08002be10318}\\0002']>
            <DisplayDevice[name='\\\\.\\DISPLAY2\\Monitor0' description='LG FULLHD(HDMI)' id='MONITOR\\GSM5ABB\\{4d36e96e-e325-11ce-bfc1-08002be10318}\\0004']>
            <DisplayDevice[name='\\\\.\\DISPLAY3\\Monitor0' description='LG FULLHD(HDMI)' id='MONITOR\\GSM5ABB\\{4d36e96e-e325-11ce-bfc1-08002be10318}\\0003']>

        :param monitor_id: A full display device ID, or a unique portion of it.  In the above example, ``SAM0F9C`` could
          be used to uniquely identify ``DISPLAY1\\Monitor0``, but ``GSM5ABB`` matches both LG monitors, so a longer
          portion of the ID would need to be provided.
        :return: The :class:`WindowsVCP` object representing the specified monitor.
        :raise: :class:`ValueError` if the specified ID is ambiguous or does not match any active monitors.
        """
        if not cls._monitors:
            cls._get_monitors()
        monitor_id = monitor_id.upper()
        try:
            return cls._monitors[monitor_id]
        except KeyError:
            pass
        if id_matches := {mid for mid in cls._monitors if monitor_id in mid}:
            if len(id_matches) == 1:
                return cls._monitors[next(iter(id_matches))]
            raise ValueError(f'Invalid {monitor_id=} - found {len(id_matches)} matches: {id_matches}')
        raise ValueError(f'Invalid {monitor_id=} - found no matches')

    @classmethod
    def _get_monitors(cls) -> list[WindowsVCP]:
        if not cls._monitors:
            handles = {info.name: handle for info, handle in get_monitor_info_and_handles()}
            displays = {dev.adapter.dev.name: dev for dev in get_active_monitors()}
            cls._monitors = {
                mon.id.upper(): WindowsVCP(n, handles[adapter_id], mon)
                for n, adapter_id in enumerate(sorted(handles))
                if (mon := displays[adapter_id])
            }

        return sorted(cls._monitors.values())

    @classmethod
    def _close(cls, monitor: PhysicalMonitor):
        """Close the handle, if it exists"""
        monitor.close()

    @cached_property
    def _monitor(self) -> PhysicalMonitor:
        monitor = PhysicalMonitor.for_handle(self._handle)
        self._finalizer = finalize(self, self._close, monitor)
        return monitor

    @property
    def description(self) -> str:
        return self._monitor.description

    @cached_property
    def capabilities(self) -> Optional[str]:
        """
        Example:
            (prot(monitor)type(lcd)SAMSUNGcmds(01 02 03 07 0C E3 F3)vcp(02 04 60( 12 0F 10) FD)mccs_ver(2.1)mswhql(1))

        (
            prot(monitor)
            type(lcd)
            SAMSUNG
            cmds(01 02 03 07 0C E3 F3)
            vcp(02 04 05 08 10 12 14(05 08 0B 0C) 16 18 1A 52 60( 12 0F 10) AA(01 02 03 FF) AC AE B2 B6 C6 C8 C9 D6(01 04 05) DC(00 02 03 05 ) DF FD)
            mccs_ver(2.1)
            mswhql(1)
        )
        """
        try:
            return self._monitor.get_capabilities()
        except OSError as e:
            log.error(e)
            return None

    def set_feature_value(self, feature: FeatureOrId, value: int):
        """
        Sets the value of a feature on the virtual control panel.

        :param feature: Feature code
        :param value: Feature value
        """
        feature = self.get_feature(feature)
        try:
            if not dxva2.SetVCPFeature(self._monitor.handle, BYTE(feature.code), DWORD(value)):
                raise WinError()
        except OSError as e:
            raise VCPError(f'Error setting VCP {feature=!r} to {value=!r}: {e}') from e

    def save_settings(self):
        try:
            self._monitor.save_settings()
        except OSError as e:
            raise VCPError('Error saving current settings') from e

    def get_feature_value(self, feature: FeatureOrId) -> tuple[int, int]:
        """
        Gets the value of a feature from the virtual control panel.

        :param feature: Feature code
        :return: Tuple of the current value, and its maximum value
        """
        feature = self.get_feature(feature)
        feature_current = DWORD()
        feature_max = DWORD()
        code_type = MC_VCP_CODE_TYPE()
        try:
            if not dxva2.GetVCPFeatureAndVCPFeatureReply(
                self._monitor.handle,
                BYTE(feature.code),
                byref(code_type),
                byref(feature_current),
                byref(feature_max),
            ):
                raise WinError()
        except OSError as e:
            raise VCPError(f'Error getting VCP {feature=!r}: {e}') from e

        log.debug(f'{feature=!r} type: {code_type.MC_MOMENTARY=}, {code_type.MC_SET_PARAMETER=}')
        return feature_current.value, feature_max.value


class Adapter:
    __slots__ = ('n', 'dev', 'monitors')
    monitors: list[DisplayDevice]

    def __init__(self, n: int, dev: DisplayDevice):
        self.n = n
        self.dev = dev
        self.monitors = []

    def __repr__(self) -> str:
        return (
            f'<Adapter#{self.n}[name={self.dev.name!r} description={self.dev.description!r}'
            f' state={self.dev.state!r} id={self.dev.id!r} key={self.dev.key!r}]>'
        )

    def __iter__(self) -> Iterator[DisplayDevice]:
        yield from self.monitors


def get_monitor_info_and_handles() -> list[tuple[MonitorInfo, int]]:
    handles = []

    def _callback(handle: int, dev_ctx_handle: HDC, rect: LPRECT, data: LPARAM):
        handles.append(handle)
        return True  # continue enumeration

    try:
        callback = WINFUNCTYPE(BOOL, HMONITOR, HDC, POINTER(RECT), LPARAM)(_callback)
        if not user32.EnumDisplayMonitors(0, 0, callback, 0):
            raise WinError()
    except OSError as e:
        raise VCPError('Failed to enumerate VCPs') from e

    return [(MonitorInfo.for_handle(handle), handle) for handle in handles]


def get_display_devices() -> list[Adapter]:
    enum_display_devices = user32.EnumDisplayDevicesW
    enum_display_devices.restype = c_bool
    adapters = []
    a = 0
    while enum_display_devices(None, a, byref(adapter_dev := DisplayDevice()), 0):
        adapter = Adapter(a, adapter_dev)
        adapter_dev.adapter = adapter_dev
        adapters.append(adapter)
        while enum_display_devices(adapter_dev.name, len(adapter.monitors), byref(dev := DisplayDevice()), 0):
            dev.adapter = adapter
            adapter.monitors.append(dev)
        a += 1

    return adapters


def get_active_monitors() -> list[DisplayDevice]:
    return [mon for adapter in get_display_devices() for mon in adapter if mon.state & MonitorState.ACTIVE]
