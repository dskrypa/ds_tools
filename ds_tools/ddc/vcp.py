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
from typing import List, Optional, Tuple, Union, Dict, MutableSet
from weakref import finalize

if sys.platform == 'win32':
    from ctypes.wintypes import (DWORD, RECT, BOOL, HMONITOR, HDC, LPARAM, HANDLE, BYTE, WCHAR)
else:
    DWORD, RECT, BOOL, HMONITOR, HDC, LPARAM, HANDLE, BYTE, WCHAR = (None,) * 9

from .features import Feature

log = logging.getLogger(__name__)

CRG9 = 'CRG9_C49RG9xSS (DP)'


class PhysicalMonitor(ctypes.Structure):
    _fields_ = [('handle', HANDLE), ('description', WCHAR * 128)]


class MC_VCP_CODE_TYPE(ctypes.Structure):
    _fields_ = [('MC_MOMENTARY', DWORD), ('MC_SET_PARAMETER', DWORD)]


class VCPError(Exception):
    """Base class for all VCP related errors."""
    pass


class VcpFeature:
    def __init__(self, code: int):
        self.code = code

    def __set_name__(self, owner, name):
        self.name = name

    def __get__(self, instance: 'WindowsVCP', owner):
        return instance.get_feature_value(self.code)

    def __set__(self, instance: 'WindowsVCP', value: int):
        instance.set_feature_value(self.code, value)


class WindowsVCP:
    """
    Windows API access to a monitor's virtual control panel.

    References: https://stackoverflow.com/questions/16588133/
    """
    _monitors = []
    input = VcpFeature(0x60)

    def __init__(self, hmonitor: HMONITOR):
        """
        :param hmonitor: logical monitor handle
        """
        self._hmonitor = hmonitor
        self.__finalizer = finalize(self, self.__close)

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

    def __getitem__(self, feature: Union[str, int, Feature]):
        return self.get_feature_value(feature)

    def __setitem__(self, feature: Union[str, int, Feature], value: int):
        return self.set_feature_value(feature, value)

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

    def get_feature(self, feature: Union[str, int, Feature]) -> Feature:
        if isinstance(feature, Feature):
            return feature
        elif isinstance(feature, int):
            return Feature.for_code(feature, self.description)
        try:
            return Feature.for_name(feature, self.description)
        except KeyError:
            try:
                return Feature.for_code(int(feature, 16), self.description)
            except ValueError:
                raise ValueError(f'Invalid VCP feature: {feature!r}')

    def get_feature_value_name(self, feature: Union[str, int, Feature], value: int, default: Optional[str] = None):
        try:
            return self.get_feature(feature).value_names.get(value, default)
        except KeyError:
            return default

    def normalize_feature_value(self, feature: Union[str, int, Feature], value: Union[str, int]) -> int:
        try:
            return int(value, 16)
        except ValueError:
            try:
                return self.get_feature(feature).name_value_map[value]
            except KeyError:
                raise ValueError(f'Unexpected feature {value=!r}')

    @cached_property
    def supported_vcp_values(self) -> Dict[Feature, MutableSet[int]]:
        supported = {}
        if supported_str := self.info.get('vcp'):
            for m in re.finditer(r'([0-9A-F]{2})(?:\(\s*([^)]+)\)|\s|$|(?=[0-9A-F]))', supported_str):
                code, values = m.groups()
                feature = self.get_feature(code)
                if feature.model or not values:
                    supported[feature] = set(feature.value_names)
                else:
                    supported[feature] = {int(v, 16) for v in values.split()}

        return supported

    def feature_value_map(self, feature: Union[str, int, Feature]):
        try:
            return self.get_feature(feature).value_names
        except (KeyError, ValueError):
            return {}

    def get_supported_values(self, feature: Union[str, int, Feature]) -> Dict[str, str]:
        feature = self.get_feature(feature)
        if int_values := self.supported_vcp_values.get(feature):
            val_name_map = feature.value_names
            return {f'0x{key:02X}': val_name_map.get(key, '[unknown]') for key in sorted(int_values)}
        else:
            return {}

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

    def get_feature_value_with_names(self, feature: Union[str, int, Feature]):
        feat_obj = self.get_feature(feature)
        current, max_val = self.get_feature_value(feat_obj.code)
        cur_name = self.get_feature_value_name(feat_obj, current)
        max_name = self.get_feature_value_name(feat_obj, max_val)
        return current, cur_name, max_val, max_name
