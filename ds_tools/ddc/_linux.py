"""
Originally based on `monitorcontrol.vcp.vcp_linux <https://github.com/newAM/monitorcontrol>`_
"""

import ctypes
import logging
import os
import struct
import sys
import time
from functools import cached_property, wraps, reduce
from operator import xor
from pathlib import Path
from typing import List, Optional, Union, Tuple

if sys.platform.startswith('linux'):
    import fcntl
else:
    fcntl = None

from .exceptions import VCPPermissionError, VCPIOError
from .features import Feature
from .vcp import VCP

__all__ = ['LinuxVCP']
log = logging.getLogger(__name__)

# fmt: off
I2C_RDWR = 0x0707   # ioctl definition
MAGIC_1 = 0x51      # = 81      first byte to send, host address
MAGIC_2 = 0x80      # = 128     second byte to send, or'd with length
MAGIC_XOR = 0x50    # = 80      initial xor for received frame
EDID_ADDR = 0x50    # = 80
DDCCI_ADDR = 0x37   # = 55
DDCCI_CHECK = 0x6E  # = 110 = DDCCI_ADDR << 1
# DELAY = 0.2
DELAY = 0.05
# fmt: on


def rate_limited(method):
    @wraps(method)
    def wrapper(self, *args, **kwargs):
        delay = self.last_write + DELAY - time.monotonic()  # Must wait at least 50 ms between messages
        if delay > 0:
            log.debug(f'Sleeping for {delay=} seconds')
            time.sleep(delay)

        return method(self, *args, **kwargs)

    return wrapper


class i2c_msg(ctypes.Structure):
    _fields_ = [
        ('addr', ctypes.c_ushort),
        ('flags', ctypes.c_ushort),
        ('len', ctypes.c_ushort),
        ('buf', ctypes.c_char_p),
    ]


class ioctl_data(ctypes.Structure):
    _fields_ = [('msgs', ctypes.c_void_p), ('nmsgs', ctypes.c_uint)]


class VcpRequest:
    def __init__(self, name: str, req_code: int, resp_code: int):
        self.name = name
        self.req_code = req_code
        self.resp_code = resp_code


Capabilities = VcpRequest('capabilities', 0xF3, 0xE3)
Identity = VcpRequest('identity', 0xF1, 0xE1)


class LinuxVCP(VCP):
    _monitors = []

    def __init__(self, path: str, ignore_checksum_errors: bool = True):
        super().__init__()
        self.path = path  # /dev/i2c-*
        self.last_write = 0
        self.ignore_checksum_errors = ignore_checksum_errors

    @rate_limited
    def _i2c(self, buf, action: int, addr: int = DDCCI_ADDR):
        msg = i2c_msg(addr, action, len(buf), ctypes.addressof(buf))
        data = ioctl_data(ctypes.addressof(msg), 1)
        act_str = 'read' if action else 'write'
        log.debug(f'Sending I2C {act_str} request with {buf.raw=}')
        if action:
            resp = fcntl.ioctl(self._fd, I2C_RDWR, data, True)  # noqa
            log.debug(f'{act_str}({action:02X}, mutate=True) {resp=}\n{buf.raw=}')
        else:
            resp = fcntl.ioctl(self._fd, I2C_RDWR, data)  # noqa
            log.debug(f'{act_str}({action:02X}) {resp=}\n{buf.raw=}')

        if resp != 1:
            act_str = 'read' if action else 'write'
            raise IOError(f'I2C {act_str} failed with code={resp}')

    def i2c_write(self, buf, addr: int = DDCCI_ADDR):
        self._i2c(buf, 0x00, addr)
        self.last_write = time.monotonic()

    def i2c_read(self, length, addr: int = DDCCI_ADDR) -> bytes:
        buf = ctypes.create_string_buffer(length)
        self._i2c(buf, 0x01, addr)
        return buf.raw

    def write(self, msg: bytes):
        buf = ctypes.create_string_buffer(len(msg) + 3)
        buf[0] = MAGIC_1
        buf[1] = MAGIC_2 | len(msg)
        buf[2:-1] = msg
        buf[-1] = reduce(xor, buf.raw, DDCCI_CHECK)  # checksum
        return self.i2c_write(buf)

    def read(self, length: int):
        resp = self.i2c_read(length + 3)
        data_len = resp[1] & ~MAGIC_2
        log.debug(f'Received read response with len={len(resp)} src=0x{resp[0]:02X} {data_len=}')
        if resp[0] != DDCCI_CHECK or resp[1] == data_len:  # Orig: resp[1] & MAGIC_2 == 0
            raise IOError(f'Invalid header in I2C response: {resp[0]:02X}{resp[1]:02X} (full {resp=})')
        elif data_len > length or data_len + 3 > len(resp):
            raise IOError(f'Invalid I2C response len={data_len} (full {resp=})')
        elif (checksum := reduce(xor, resp[:data_len + 3], MAGIC_XOR)) != 0:
            raise IOError(f'Checksum error for I2C response ({checksum=:02X}, full {resp=})')
        return resp[2:data_len + 2]

    def request(self, op: int, ctrl: int = 0x00, value: Optional[int] = None) -> Optional[Tuple[int, int]]:
        req = bytearray(struct.pack('BB', op, ctrl))
        if value is not None:
            req.extend(reversed(struct.pack('H', value)))
        self.write(req)
        if value is None:
            resp = self.read(8)
            resp_code, result, resp_ctrl, vcp_type, max_value, current = struct.unpack(f'>BBBBHH', resp)
            log.debug(f'Response: {locals()}')
            if resp_code != 0x02:
                raise VCPIOError(f'Received unexpected response code: {resp_code}')
            elif resp_ctrl != ctrl:
                raise VCPIOError(f'Received unexpected ctrl code: {resp_ctrl}')
            elif result > 0:
                raise VCPIOError('Unsupported VCP code' if result == 1 else f'Unknown {result=!r}')
            return current, max_value

    def _get_str(self, req: VcpRequest, offset: int) -> bytes:
        log.debug(f'Requesting {req.name} with {offset=}')
        header = struct.Struct('>BH')
        self.write(header.pack(req.req_code, offset))
        resp = self.read(64)
        log.debug(f'Read {len(resp)} bytes: {resp}')
        if len(resp) <= 3:
            return b''
        code, for_offset = header.unpack_from(resp)
        if code != req.resp_code or for_offset != offset:
            raise IOError(
                f'Invalid response for {req.name} request - {code=:02X}, {for_offset=} != {offset} (full {resp=})'
            )
        return resp[3:]

    def get_str(self, req: VcpRequest, retries: int = 3):
        offset = 0
        buf = bytearray()
        max_retries = retries
        while True:
            try:
                chunk = self._get_str(req, offset)
            except IOError as e:
                retries -= 1
                if retries <= 0:
                    raise
                log.debug(f'Retrying due to {e}', extra={'color': 'red'})
            else:
                retries = max_retries
                if not chunk:
                    break
                buf.extend(chunk)
                log.debug(f'Current {req.name} buffer={buf.decode("utf-8")!r}')
                offset += len(chunk)

        result = buf.decode('utf-8')
        return result.rstrip('\x00')

    @cached_property
    def capabilities(self) -> Optional[str]:
        return self.get_str(Capabilities)

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

    def set_feature_value(self, feature: Union[str, int, Feature], value: int):
        feature = self.get_feature(feature)
        return self.request(0x03, feature.code, value)

    def get_feature_value(self, feature: Union[str, int, Feature]) -> Tuple[int, int]:
        feature = self.get_feature(feature)
        return self.request(0x01, feature.code)

    def get_raw(self):
        time.sleep(0.04)  # Must wait at least 40 ms

        header = self._read_bytes(2)
        source, length = struct.unpack('BB', header)
        length &= ~0x80  # clear protocol flag
        return self._read_bytes(length + 1)

    def get_checked(self) -> bytes:
        header = self._read_bytes(2)
        source, length = struct.unpack('BB', header)
        length &= ~0x80  # clear protocol flag
        log.debug(f'Received {header=} -> {source=:02X} {length=}')
        payload = self._read_bytes(length + 1)
        log.debug(f'Received {len(payload)} bytes in raw {payload=}')

        payload, checksum = struct.unpack(f'{length}sB', payload)
        if checksum_xor := checksum ^ get_checksum(header + payload):
            if self.ignore_checksum_errors:
                log.warning(f'Checksum does not match: {checksum_xor}')
            else:
                raise VCPIOError(f'Checksum does not match: {checksum_xor}')
        return payload

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
