from __future__ import annotations

from ctypes import Structure, c_ushort, c_uint, c_char_p, c_void_p


class i2c_msg(Structure):
    _fields_ = [('addr', c_ushort), ('flags', c_ushort), ('len', c_ushort), ('buf', c_char_p)]


class ioctl_data(Structure):
    _fields_ = [('msgs', c_void_p), ('nmsgs', c_uint)]
