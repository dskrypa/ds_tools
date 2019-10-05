"""
Utilities to simplify hashing of large files

:author: Doug Skrypa
"""

import hashlib
from pathlib import Path

__all__ = ['sha512sum']


def sha512sum(file_path, block_size=10485760):
    """
    :param str|Path file_path: The path to a file to hash
    :param int block_size: Number of bytes to read from the file at a time (default: 10MB)
    :return str: The hex representation of the given file's sha512 hash
    """
    if not isinstance(file_path, Path):
        file_path = Path(file_path)
    sha512 = hashlib.sha512()
    with file_path.open('rb') as f:
        buf = f.read(block_size)
        while len(buf) > 0:
            sha512.update(buf)
            buf = f.read(block_size)
    return sha512.hexdigest()
