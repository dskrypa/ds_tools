from __future__ import annotations

import logging
import os
from ctypes import addressof, create_string_buffer, Array, c_char
from functools import wraps, reduce
from operator import xor
from pathlib import Path
from struct import Struct, pack, unpack
from time import sleep, monotonic
from typing import Callable, TypeVar, ParamSpec
from weakref import finalize

try:
    from fcntl import ioctl
except ImportError:
    ioctl = None

from ds_tools.core.mixins import Finalizable
from ..exceptions import VCPIOError, VCPPermissionError
from .constants import I2C_RDWR, MAGIC_1, MAGIC_2, MAGIC_XOR, EDID_ADDR, DDCCI_ADDR, DDCCI_CHECK
from .constants import DELAY
from .structs import i2c_msg, ioctl_data

__all__ = ['I2CFile', 'I2CIoctlClient', 'DDCCIClient', 'Capabilities', 'Identity']
log = logging.getLogger(__name__)

T = TypeVar('T')
P = ParamSpec('P')


def rate_limited(method: Callable[P, T]) -> Callable[P, T]:
    @wraps(method)
    def wrapper(self: I2CFileClient, *args, **kwargs):
        delay = self.file.last_write + DELAY - monotonic()  # Must wait at least 50 ms between messages
        if delay > 0:
            log.debug(f'Sleeping for {delay=} seconds')
            sleep(delay)

        return method(self, *args, **kwargs)

    return wrapper


class I2CFile(Finalizable):
    __slots__ = ('fd', 'path', 'last_write')

    def __init__(self, path: Path):
        self.path = path
        self.last_write = 0
        try:
            self.fd = fd = os.open(self.path, os.O_RDWR)
            # I2C bus address, DDC-CI command address on the I2C bus
            ioctl(fd, 0x0703, 0x37)
        except PermissionError as e:
            raise VCPPermissionError(self.path) from e
        except OSError as e:
            raise VCPIOError(f'Unable to open VCP at {self.path}') from e
        self._finalizer = finalize(self, self._close, fd, self.path)
        try:
            os.read(fd, 1)
        except OSError as e:
            raise VCPIOError('Unable to read from I2C bus') from e

    @classmethod
    def _close(cls, fd: int, path: Path):
        try:
            os.close(fd)
        except OSError as e:
            raise VCPIOError(f'Unable to close {path}') from e


class I2CFileClient:
    __slots__ = ('file',)

    def __init__(self, file: I2CFile):
        self.file = file


class I2CIoctlClient(I2CFileClient):
    __slots__ = ()

    @rate_limited
    def _ioctl(self, buf: Array[c_char], flags: int, addr: int = DDCCI_ADDR):
        msg = i2c_msg(addr, flags, len(buf), addressof(buf))
        data = ioctl_data(addressof(msg), 1)
        act_str = 'read' if flags else 'write'
        log.debug(f'Sending I2C {act_str} request with {buf.raw=}')
        if flags:
            resp = ioctl(self.file.fd, I2C_RDWR, data, True)
            log.debug(f'{act_str}({flags:02X}, mutate=True) {resp=}\n{buf.raw=}')
        else:
            resp = ioctl(self.file.fd, I2C_RDWR, data)
            log.debug(f'{act_str}({flags:02X}) {resp=}\n{buf.raw=}')

        if resp != 1:
            raise IOError(f'I2C {act_str} failed with code={resp}')

    def write(self, buf: Array[c_char], addr: int = DDCCI_ADDR):
        self._ioctl(buf, 0x00, addr)
        self.file.last_write = monotonic()

    def read(self, length: int, addr: int = DDCCI_ADDR) -> bytes:
        buf = create_string_buffer(length)
        self._ioctl(buf, 0x01, addr)
        return buf.raw

    def read_edid(self, size: int = 256, write_before_read: bool = True) -> bytes:
        if write_before_read:
            self.write(create_string_buffer(1), EDID_ADDR)
        return self.read(size, EDID_ADDR)


# region DDC-CI


class DDCCIClient:
    __slots__ = ('ioctl_client',)

    def __init__(self, file_or_client: I2CFile | I2CIoctlClient):
        if isinstance(file_or_client, I2CFile):
            file_or_client = I2CIoctlClient(file_or_client)
        self.ioctl_client = file_or_client

    def request(self, op: int, ctrl: int = 0x00, value: int | None = None) -> tuple[int, int] | None:
        """
        :param op:
        :param ctrl:
        :param value:
        """
        req = bytearray(pack('BB', op, ctrl))
        if value is not None:
            req.extend(reversed(pack('H', value)))
        self._write(req)
        if value is None:
            resp = self._read(8)
            resp_code, result, resp_ctrl, vcp_type, max_value, current = unpack(f'>BBBBHH', resp)
            log.debug(f'Response: {locals()}')
            if resp_code != 0x02:
                raise VCPIOError(f'Received unexpected response code: {resp_code}')
            elif resp_ctrl != ctrl:
                raise VCPIOError(f'Received unexpected ctrl code: {resp_ctrl}')
            elif result > 0:
                raise VCPIOError('Unsupported VCP code' if result == 1 else f'Unknown {result=!r}')
            return current, max_value

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

    def _get_str(self, req: VcpRequest, offset: int) -> bytes:
        log.debug(f'Requesting {req.name} with {offset=}')
        header = Struct('>BH')
        self._write(header.pack(req.req_code, offset))
        resp = self._read(64)
        log.debug(f'Read {len(resp)} bytes: {resp}')
        if len(resp) <= 3:
            return b''
        code, for_offset = header.unpack_from(resp)
        if code != req.resp_code or for_offset != offset:
            raise IOError(
                f'Invalid response for {req.name} request - {code=:02X}, {for_offset=} != {offset} (full {resp=})'
            )
        return resp[3:]

    def _write(self, msg: bytes):
        buf = create_string_buffer(len(msg) + 3)
        buf[0] = MAGIC_1
        buf[1] = MAGIC_2 | len(msg)
        buf[2:-1] = msg
        buf[-1] = reduce(xor, buf.raw, DDCCI_CHECK)  # checksum
        return self.ioctl_client.write(buf)

    def _read(self, length: int) -> bytes:
        resp = self.ioctl_client.read(length + 3)
        data_len = resp[1] & ~MAGIC_2
        log.debug(f'Received read response with len={len(resp)} src=0x{resp[0]:02X} {data_len=}')
        if resp[0] != DDCCI_CHECK or resp[1] == data_len:  # Orig: resp[1] & MAGIC_2 == 0
            raise IOError(f'Invalid header in I2C response: {resp[0]:02X}{resp[1]:02X} (full {resp=})')
        elif data_len > length or data_len + 3 > len(resp):
            raise IOError(f'Invalid I2C response len={data_len} (full {resp=})')
        elif (checksum := reduce(xor, resp[:data_len + 3], MAGIC_XOR)) != 0:
            raise IOError(f'Checksum error for I2C response ({checksum=:02X}, full {resp=})')
        return resp[2:data_len + 2]


class VcpRequest:
    __slots__ = ('name', 'req_code', 'resp_code')

    def __init__(self, name: str, req_code: int, resp_code: int):
        self.name = name
        self.req_code = req_code
        self.resp_code = resp_code


Capabilities = VcpRequest('capabilities', 0xF3, 0xE3)
Identity = VcpRequest('identity', 0xF1, 0xE1)


# endregion


# region File IO


class I2CFileIO(I2CFileClient):
    # This is not currently used
    __slots__ = ('ignore_checksum_errors',)

    def __init__(self, file: I2CFile, ignore_checksum_errors: bool = True):
        super().__init__(file)
        self.ignore_checksum_errors = ignore_checksum_errors

    def get_raw(self) -> bytes:
        sleep(0.04)  # Must wait at least 40 ms

        header = self._read_bytes(2)
        source, length = unpack('BB', header)
        length &= ~0x80  # clear protocol flag
        log.debug(f'Received {header=} -> {source=:02X} {length=}')
        return self._read_bytes(length + 1)

    def get_checked(self) -> bytes:
        header = self._read_bytes(2)
        source, length = unpack('BB', header)
        length &= ~0x80  # clear protocol flag
        log.debug(f'Received {header=} -> {source=:02X} {length=}')
        payload = self._read_bytes(length + 1)
        log.debug(f'Received {len(payload)} bytes in raw {payload=}')

        payload, checksum = unpack(f'{length}sB', payload)
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
            return os.read(self.file.fd, num_bytes)
        except OSError as e:
            raise VCPIOError('Unable to read from I2C bus') from e

    @rate_limited
    def _write_bytes(self, data: bytes):
        """Writes bytes to the I2C bus."""
        try:
            os.write(self.file.fd, data)
        except OSError as e:
            raise VCPIOError('Unable write to I2C bus') from e


def get_checksum(data: bytes) -> int:
    checksum = 0x50
    for data_byte in data:
        checksum ^= data_byte
    return checksum


# endregion
