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
import re
import sys
from functools import cached_property
from typing import List, Optional, Tuple
from weakref import finalize

if sys.platform == 'win32':
    from ctypes.wintypes import (DWORD, RECT, BOOL, HMONITOR, HDC, LPARAM, HANDLE, BYTE, WCHAR)
else:
    DWORD, RECT, BOOL, HMONITOR, HDC, LPARAM, HANDLE, BYTE, WCHAR = (None,) * 9

log = logging.getLogger(__name__)


class PhysicalMonitor(ctypes.Structure):
    _fields_ = [('handle', HANDLE), ('description', WCHAR * 128)]


class VCPError(Exception):
    """Base class for all VCP related errors."""
    pass


class WindowsVCP:
    """
    Windows API access to a monitor's virtual control panel.

    References: https://stackoverflow.com/questions/16588133/
    """
    _monitors = []

    def __init__(self, hmonitor: HMONITOR):
        """
        :param hmonitor: logical monitor handle
        """
        self._hmonitor = hmonitor
        self.__finalizer = finalize(self, self.__close)

    def __repr__(self):
        return f'<{self.__class__.__name__}[hmonitor={self._hmonitor}]>'

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

    def close(self):
        try:
            finalizer = self.__finalizer
        except AttributeError:
            pass  # This happens if an exception was raised in __init__
        else:
            if finalizer.detach():
                self.__close()

    def __del__(self):
        self.close()

    def __close(self):
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

    def __enter__(self) -> 'WindowsVCP':
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def __getitem__(self, item: int):
        return self.get_vcp_feature(item)

    def __setitem__(self, key: int, value: int):
        return self.set_vcp_feature(key, value)

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

    @cached_property
    def info(self):
        info = {}
        if self.capabilities:
            for m in re.finditer(r'(([a-z_]+)\(([a-zA-Z0-9.]+|[0-9A-F(). ]+)\)|[A-Z]+)', self.capabilities):
                brand, token, value = m.groups()
                if not token and not value:
                    info['brand'] = brand
                else:
                    info[token] = value

        return info

    @cached_property
    def type(self):
        return self.info.get('type')

    @cached_property
    def model(self):
        return self.info.get('model')

    @cached_property
    def supported_vcp_values(self):
        supported = {}
        if supported_str := self.info.get('vcp'):
            for m in re.finditer(r'([0-9A-F]{2})(?:\(\s*([^)]+)\)|\s|$|(?=[0-9A-F]))', supported_str):
                code, values = m.groups()
                if not values:
                    supported[f'0x{code}'] = '*'
                else:
                    supported[f'0x{code}'] = {f'0x{v}' for v in values.split()}

        return supported

    def set_vcp_feature(self, code: int, value: int):
        """
        Sets the value of a feature on the virtual control panel.

        :param code: Feature code
        :param value: Feature value
        """
        try:
            if not ctypes.windll.dxva2.SetVCPFeature(HANDLE(self.handle), BYTE(code), DWORD(value)):
                raise ctypes.WinError()
        except OSError as e:
            raise VCPError(f'Error setting VCP {code=!r} to {value=!r}') from e

    def get_vcp_feature(self, code: int) -> Tuple[int, int]:
        """
        Gets the value of a feature from the virtual control panel.

        :param code: Feature code
        :return: Tuple of the current value, and its maximum value
        """
        feature_current = DWORD()
        feature_max = DWORD()
        try:
            if not ctypes.windll.dxva2.GetVCPFeatureAndVCPFeatureReply(
                HANDLE(self.handle),
                BYTE(code),
                None,
                ctypes.byref(feature_current),
                ctypes.byref(feature_max),
            ):
                raise ctypes.WinError()
        except OSError as e:
            raise VCPError(f'Error getting VCP {code=!r}') from e

        return feature_current.value, feature_max.value
