"""

"""

from __future__ import annotations

from os import SEEK_END, SEEK_SET
from typing import BinaryIO


def get_size(f: BinaryIO) -> int:
    """
    Get the size of the given IO stream.  Stores the position at the time this function was called, and returns the
    pointer to that position before returning the size.
    """
    pos = f.tell()
    f.seek(0, SEEK_END)
    size = f.tell()
    f.seek(pos, SEEK_SET)
    return size
