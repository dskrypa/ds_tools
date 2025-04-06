from __future__ import annotations

import logging
from functools import cached_property

from ..exceptions import VCPIOError

__all__ = ['Edid']
log = logging.getLogger(__name__)

DESC_TYPES = {0xff: 'serial_number', 0xfe: 'other', 0xfc: 'model'}


class EdidProperty:
    def __init__(self, offset: int | slice, func=None):
        self.offset = offset
        self.func = func

    def __set_name__(self, owner, name):
        self.name = name
        owner._properties.add(name)  # noqa

    def __get__(self, instance, owner):
        if instance is None:
            return self

        data = instance.data[self.offset]
        if self.func is not None:
            data = self.func(data)
        instance.__dict__[self.name] = data
        return data


class Edid:
    _properties = set()
    product_code: int = EdidProperty(slice(10, 12), lambda d: d[1] << 8 | d[0])
    binary_serial_number: int = EdidProperty(slice(12, 16), lambda d: d[0] | d[1] << 8 | d[2] << 16 | d[3] << 24)
    year: int = EdidProperty(17, lambda d: d + 1990)
    is_model_year: bool = EdidProperty(16, lambda d: d == 0xff)
    manufacture_week: int = EdidProperty(16)
    edid_version: str = EdidProperty(slice(18, 20), lambda d: f'{d[0]}.{d[1]}')
    video_input_definition: int = EdidProperty(14)
    supported_features: int = EdidProperty(18)
    extension_flag: int = EdidProperty(126)

    def __init__(self, data: bytes):
        if (start := data.index(b'\x00\xff\xff\xff\xff\xff\xff\x00')) < 0:
            raise VCPIOError(f'Invalid EDID data was read')
        self.data = data[start : start + 256]

    @cached_property
    def manufacturer(self) -> str:
        """The 2-byte manufacturer ID, unpacked to a 3-char string."""
        a, b = self.data[8:10]
        chars = ((a >> 2) & 0x1F, ((a & 0x03) << 3) | ((b >> 5) & 0x07), b & 0x1F)
        return ''.join(chr(c + 64) for c in chars)

    @cached_property
    def _descriptors(self):
        descriptors = {}
        for start in range(54, 127, 18):  # There are 4x 18-byte descriptor fields, starting at offset=54
            desc = self.data[start : start + 18]
            if desc[:3] == b'\x00\x00\x00' and desc[4] == 0 and (desc_type := DESC_TYPES.get(desc[3])):
                descriptors[desc_type] = desc[5:].decode('utf-8').rstrip()
            else:
                log.debug(f'Skipping invalid edid descriptor={desc!r}')
        return descriptors

    @cached_property
    def model(self) -> str | None:
        return self._descriptors.get('model')

    @cached_property
    def serial_number(self) -> str | None:
        return self._descriptors.get('serial_number')

    @cached_property
    def product_code_hex(self) -> str:
        return f'{self.product_code:04X}'

    @cached_property
    def serial_number_repr(self) -> str:
        if self.serial_number and self.binary_serial_number:
            return f'# {self.serial_number} / {self.binary_serial_number}'
        num = self.serial_number or self.binary_serial_number or 'UNKNOWN'
        return f'# {num}'

    def as_dict(self):
        keys = ['manufacturer', 'model', 'serial_number', 'product_code_hex'] + sorted(self._properties)
        return {key: getattr(self, key) for key in keys}
