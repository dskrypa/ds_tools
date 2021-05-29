"""
Misc utilities related to working with binary data.

:author: Doug Skrypa
"""

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
