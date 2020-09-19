"""
Utilities to simplify hashing of large files

:author: Doug Skrypa
"""

import hashlib

__all__ = ['sha512sum']


def sha512sum(file_path, block_size=10485760):
    """
    :param str|Path file_path: The path to a file to hash
    :param int block_size: Number of bytes to read from the file at a time (default: 10MB)
    :return str: The hex representation of the given file's sha512 hash
    """
    sha512 = hashlib.sha512()
    with open(file_path, 'rb') as f:
        while buf := f.read(block_size):
            sha512.update(buf)
    return sha512.hexdigest()
