"""
Originally based on `monitorcontrol.vcp.vcp_linux <https://github.com/newAM/monitorcontrol>`_
"""

import logging
import os
import struct
import sys
import time
from functools import cached_property, wraps
from pathlib import Path
from typing import List, Optional, Tuple, Union

if sys.platform.startswith('linux'):
    import fcntl
else:
    fcntl = None

from .exceptions import VCPPermissionError, VCPIOError
from .features import Feature
from .vcp import VCP

__all__ = ['LinuxVCP']
log = logging.getLogger(__name__)


def rate_limited(method):
    @wraps(method)
    def wrapper(self, *args, **kwargs):
        if self.last_set is not None:
            rate_delay = 0.05 - time.monotonic() - self.last_set  # Must wait at least 50 ms between messages
            if rate_delay > 0:
                time.sleep(rate_delay)

        return method(self, *args, **kwargs)

    return wrapper


class LinuxVCP(VCP):
    _monitors = []

    def __init__(self, path: str, ignore_checksum_errors: bool = True):
        super().__init__()
        self.path = path  # /dev/i2c-*
        self.last_set: Optional[float] = None  # time of last feature set call
        self.ignore_checksum_errors = ignore_checksum_errors

    def capabilities(self) -> Optional[str]:
        return ''

    @property
    def description(self):
        return None

    def save_settings(self):
        pass

    @classmethod
    def get_monitors(cls, ignore_checksum_errors: bool = True) -> List['LinuxVCP']:
        if not cls._monitors:
            for path in Path('/dev').glob('i2c-*'):
                vcp = cls(path.as_posix(), ignore_checksum_errors)
                try:
                    vcp._fd  # noqa
                except (OSError, VCPIOError):
                    pass
                else:
                    cls._monitors.append(vcp)
        return cls._monitors

    @cached_property
    def _fd(self):
        try:
            fd = os.open(self.path, os.O_RDWR)
            # I2C bus address, DDC-CI command address on the I2C bus
            fcntl.ioctl(fd, 0x0703, 0x37)
        except PermissionError as e:
            raise VCPPermissionError(f'Permission error for {self.path}') from e
        except OSError as e:
            raise VCPIOError(f'Unable to open VCP at {self.path}') from e
        try:
            os.read(fd, 1)
        except OSError as e:
            raise VCPIOError('Unable to read from I2C bus') from e
        return fd

    def _close(self):
        try:
            fd = self.__dict__['_fd']
        except KeyError:
            pass
        else:
            log.debug(f'Closing {self}')
            try:
                os.close(fd)
            except OSError as e:
                raise VCPIOError(f'Unable to close {self.path}') from e

            del self.__dict__['_fd']

    def get_capabilities(self):
        # https://github.com/rockowitz/ddcutil/blob/df01384dc91639a3d65f6d31ec40ee11ebdd9a5d/src/base/ddc_packets.h#L95
        self._send(0xf3, 0x00)
        reply_code, result_code, vcp_opcode, vcp_type_code, capabilities = self._get(0xe3, 's')
        return capabilities

    def _save(self):
        self._send(0x0c, 0x00)

    def _get_id(self):
        # https://github.com/rockowitz/ddcutil/blob/df01384dc91639a3d65f6d31ec40ee11ebdd9a5d/src/base/ddc_packets.h#L97
        self._send(0xf1, 0x00)
        reply_code, result_code, vcp_opcode, vcp_type_code, _id = self._get(0xe1, 's')
        return _id

    def set_feature_value(self, feature: Union[str, int, Feature], value: int):
        feature = self.get_feature(feature)
        self._send(0x03, feature.code, value)
        self.last_set = time.monotonic()

    def get_feature_value(self, feature: Union[str, int, Feature]) -> Tuple[int, int]:
        feature = self.get_feature(feature)
        self._send(0x01, feature.code)
        reply_code, result_code, vcp_opcode, vcp_type_code, (max_val, current) = self._get(0x02, 'HH', feature.code)
        return current, max_val

    def _send(self, cmd: int, sub_cmd: int, value: Optional[int] = None):
        data = bytearray()
        data.append(cmd)
        data.append(sub_cmd)
        if value is not None:
            low_byte, high_byte = struct.pack('H', value)
            data.append(high_byte)
            data.append(low_byte)
        data.insert(0, (len(data) | 0x80))
        data.insert(0, 0x50)
        data.append(get_checksum(data))
        self._write_bytes(data)

    def _get(self, expected_reply: int, type: str, expected_op: Optional[int] = None):
        time.sleep(0.04)  # Must wait at least 40 ms

        header = self._read_bytes(2)
        source, length = struct.unpack('BB', header)
        length &= ~0x80  # clear protocol flag
        payload = self._read_bytes(length + 1)

        payload, checksum = struct.unpack(f'{length}sB', payload)
        if checksum_xor := checksum ^ get_checksum(header + payload):
            if self.ignore_checksum_errors:
                log.warning(f'Checksum does not match: {checksum_xor}')
            else:
                raise VCPIOError(f'Checksum does not match: {checksum_xor}')

        reply_code, result_code, vcp_opcode, vcp_type_code, *values = struct.unpack(f'>BBBB{type}', payload)
        if reply_code != expected_reply:
            raise VCPIOError(f'Received unexpected response code: {reply_code}')
        elif expected_op is not None and vcp_opcode != expected_op:
            raise VCPIOError(f'Received unexpected opcode: {vcp_opcode}')
        elif result_code > 0:
            raise VCPIOError('Unsupported VCP code' if result_code == 1 else f'Unknown {result_code=!r}')
        return reply_code, result_code, vcp_opcode, vcp_type_code, values

    @rate_limited
    def _read_bytes(self, num_bytes: int) -> bytes:
        """Reads bytes from the I2C bus."""
        try:
            return os.read(self._fd, num_bytes)
        except OSError as e:
            raise VCPIOError('Unable to read from I2C bus') from e

    @rate_limited
    def _write_bytes(self, data: bytes):
        """Writes bytes to the I2C bus."""
        try:
            os.write(self._fd, data)
        except OSError as e:
            raise VCPIOError('Unable write to I2C bus') from e


def get_checksum(data: bytes) -> int:
    checksum = 0x50
    for data_byte in data:
        checksum ^= data_byte
    return checksum
