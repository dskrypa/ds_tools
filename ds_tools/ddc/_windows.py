"""
Windows API for accessing / controlling a monitor's VCP (Virtual Control Panel).

Originally based on `monitorcontrol.vcp.vcp_windows <https://github.com/newAM/monitorcontrol>`_

Available functions:
https://docs.microsoft.com/en-us/windows/win32/monitor/monitor-configuration-functions
Funcs, structs, enums:
https://docs.microsoft.com/en-us/windows/win32/monitor/monitor-configuration-reference
"""

import ctypes
import logging
import sys
from functools import cached_property
from typing import List, Optional, Tuple, Union

if sys.platform == 'win32':
    from ctypes.wintypes import DWORD, RECT, BOOL, HMONITOR, HDC, LPARAM, HANDLE, BYTE
else:
    DWORD, RECT, BOOL, HMONITOR, HDC, LPARAM, HANDLE, BYTE = (None,) * 8

from .exceptions import VCPError
from .features import Feature
from .structs import PhysicalMonitor, MC_VCP_CODE_TYPE
from .vcp import VCP

log = logging.getLogger(__name__)


class WindowsVCP(VCP):
    """
    Windows API access to a monitor's virtual control panel.

    References: https://stackoverflow.com/questions/16588133/
    """
    _monitors = []

    def __init__(self, hmonitor: HMONITOR):
        """
        :param hmonitor: logical monitor handle
        """
        super().__init__()
        self._hmonitor = hmonitor

    def __repr__(self):
        return f'<{self.__class__.__name__}[{self.description}, hmonitor={self._hmonitor.value}]>'

    @classmethod
    def get_monitors(cls) -> List['WindowsVCP']:
        if not cls._monitors:
            hmonitors = []

            def _callback(hmonitor, hdc, lprect, lparam):
                hmonitors.append(HMONITOR(hmonitor))
                del hmonitor, hdc, lprect, lparam
                return True  # continue enumeration

            try:
                # noinspection PyTypeChecker
                callback = ctypes.WINFUNCTYPE(BOOL, HMONITOR, HDC, ctypes.POINTER(RECT), LPARAM)(_callback)
                if not ctypes.windll.user32.EnumDisplayMonitors(0, 0, callback, 0):
                    raise ctypes.WinError()
            except OSError as e:
                raise VCPError('Failed to enumerate VCPs') from e

            cls._monitors = [WindowsVCP(logical) for logical in hmonitors]

        return cls._monitors

    def _close(self):
        """Close the handle, if it exists"""
        try:
            monitor = self.__dict__['_monitor']
        except KeyError:
            pass
        else:
            log.debug(f'Closing {self}')
            try:
                ctypes.windll.dxva2.DestroyPhysicalMonitor(monitor.handle)
            except OSError as e:
                raise VCPError('Failed to close handle') from e
            del self.__dict__['_monitor']

    @cached_property
    def _monitor(self) -> 'PhysicalMonitor':
        num_physical = DWORD()
        try:
            if not ctypes.windll.dxva2.GetNumberOfPhysicalMonitorsFromHMONITOR(
                self._hmonitor, ctypes.byref(num_physical)
            ):
                raise ctypes.WinError()
        except OSError as e:
            raise VCPError('Windows API call failed') from e

        if num_physical.value != 1:
            # The Windows API does not allow opening and closing of individual physical monitors without their hmonitors
            raise VCPError(f'Found {num_physical.value} physical monitors for hmonitor={self._hmonitor}')

        physical_monitors = (PhysicalMonitor * num_physical.value)()
        try:
            if not ctypes.windll.dxva2.GetPhysicalMonitorsFromHMONITOR(
                self._hmonitor, num_physical.value, physical_monitors
            ):
                raise ctypes.WinError()
        except OSError as e:
            raise VCPError('Failed to open physical monitor handle') from e

        return physical_monitors[0]

    @property
    def handle(self):
        return self._monitor.handle

    @property
    def description(self):
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
        cap_len = DWORD()
        if not ctypes.windll.dxva2.GetCapabilitiesStringLength(self.handle, ctypes.byref(cap_len)):
            raise ctypes.WinError()

        caps_string = (ctypes.c_char * cap_len.value)()
        if not ctypes.windll.dxva2.CapabilitiesRequestAndCapabilitiesReply(self.handle, caps_string, cap_len):
            log.error(ctypes.WinError())
            return None

        return caps_string.value.decode('ASCII')

    def set_feature_value(self, feature: Union[str, int, Feature], value: int):
        """
        Sets the value of a feature on the virtual control panel.

        :param feature: Feature code
        :param value: Feature value
        """
        feature = self.get_feature(feature)
        try:
            if not ctypes.windll.dxva2.SetVCPFeature(self.handle, BYTE(feature.code), DWORD(value)):
                raise ctypes.WinError()
        except OSError as e:
            raise VCPError(f'Error setting VCP {feature=!r} to {value=!r}: {e}') from e

    def save_settings(self):
        try:
            if not ctypes.windll.dxva2.SaveCurrentMonitorSettings(self.handle):
                raise ctypes.WinError()
        except OSError as e:
            raise VCPError('Error saving current settings') from e

    def get_feature_value(self, feature: Union[str, int, Feature]) -> Tuple[int, int]:
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
            if not ctypes.windll.dxva2.GetVCPFeatureAndVCPFeatureReply(
                HANDLE(self.handle),
                BYTE(feature.code),
                ctypes.byref(code_type),
                ctypes.byref(feature_current),
                ctypes.byref(feature_max),
            ):
                raise ctypes.WinError()
        except OSError as e:
            raise VCPError(f'Error getting VCP {feature=!r}: {e}') from e

        log.debug(f'{feature=!r} type: {code_type.MC_MOMENTARY=}, {code_type.MC_SET_PARAMETER=}')
        return feature_current.value, feature_max.value
