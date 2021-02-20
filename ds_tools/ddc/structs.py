"""
Structs for VCP

:author: Doug Skrypa
"""

import ctypes
import sys

if sys.platform == 'win32':
    from ctypes.wintypes import DWORD, HANDLE, WCHAR
else:
    DWORD, HANDLE, WCHAR = None, None, None

__all__ = ['PhysicalMonitor', 'MC_VCP_CODE_TYPE']


class PhysicalMonitor(ctypes.Structure):
    _fields_ = [('handle', HANDLE), ('description', WCHAR * 128)]


class MC_VCP_CODE_TYPE(ctypes.Structure):
    _fields_ = [('MC_MOMENTARY', DWORD), ('MC_SET_PARAMETER', DWORD)]
