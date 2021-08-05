"""
Misc utilities related to working with binary data.

:author: Doug Skrypa
"""

from enum import Enum
from struct import unpack_from, error as StructError
from typing import Union, Iterator


class BytePattern:
    """Find sequences of bytes that match the given input, where None is used as a wildcard for a single byte"""

    def __init__(self, *pattern: Union[bytes, None]):
        self._parts = []
        for obj in pattern:
            if isinstance(obj, bytes):
                self._parts.extend(obj)
            else:
                self._parts.append(None)

    def iter_matches(self, data: bytes) -> Iterator[tuple[int, bytes]]:
        data = memoryview(data)
        parts = self._parts
        chunk_len = len(parts)
        for i in range(len(data) - chunk_len):
            chunk = data[i: i + chunk_len]
            if all(p is None or b == p for b, p in zip(chunk, parts)):
                yield i, bytes(chunk)

    def all_matches(self, data: bytes) -> tuple[tuple[int, bytes], ...]:
        return tuple(self.iter_matches(data))


class Endian(Enum):
    NATIVE = '@'            # Native byte order, native size, native alignment
    NATIVE_STANDARD = '='   # Native byte order, standard size
    LITTLE = '<'            # Little-endian byte order, standard size
    BIG = '>'               # Big-endian byte order, standard size

    @classmethod
    def _missing_(cls, value):
        return cls._member_map_.get(value.upper() if isinstance(value, str) else value)


FORMATS = {
    '?': ('bool', 1),
    'b': ('int8', 1),   'h': ('int16', 2),      'i': ('int32', 4),      'q': ('int64', 8),
    'B': ('uint8', 1),  'H': ('uint16', 2),     'I': ('unit32', 4),     'Q': ('uint64', 8),
                        'e': ('float16', 2),    'f': ('float32', 4),    'd': ('float64', 8),
    # 'x': ('pad byte', 1), 'c': ('char', 1), 'l': ('int32', 4), 'L': ('uint32', 4), 's': ('string', 1),
    # 'n': ('ssize_t', calcsize('n')), 'N': ('size_t', calcsize('N')), 'P': ('pointer', calcsize('P')),  # @ only
    # 'p': ('pascal string', 1),  # 1st byte = min(len,255). struct only supports 255 char read, 254 char write.
}


def view_unpacked(data: bytes, *, split: int = 4, sep: str = ' ', offset: int = 0, endian: Endian = None):
    endian = Endian(endian or '@')
    unpacked = {'bin': sep.join(map('{:08b}'.format, data)), 'hex': data.hex(sep, split)}
    for fc, (name, width) in FORMATS.items():
        fmt = endian.value + fc
        from_struct = []
        for i in range(offset, len(data), width):
            try:
                from_struct.extend(unpack_from(fmt, data, i))
            except StructError:
                pass
        unpacked[name] = from_struct
    return unpacked
