"""
Utilities to simplify hashing of large files

:author: Doug Skrypa
"""

from __future__ import annotations

from hashlib import sha512, sha256
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .typing import PathLike

__all__ = ['sha256sum', 'sha512sum']

_DEFAULT_BLOCK_SIZE: int = 10_485_760  # 10 MB


def _hash_file(hash_cls, file_path: PathLike, block_size: int = _DEFAULT_BLOCK_SIZE) -> str:
    hash_obj = hash_cls()
    with open(file_path, 'rb') as f:
        while buf := f.read(block_size):
            hash_obj.update(buf)
    return hash_obj.hexdigest()


def sha256sum(file_path: PathLike, block_size: int = _DEFAULT_BLOCK_SIZE) -> str:
    """
    :param file_path: The path to a file to hash
    :param block_size: Number of bytes to read from the file at a time (default: 10MB)
    :return: The hex representation of the given file's sha256 hash
    """
    return _hash_file(sha256, file_path, block_size)


def sha512sum(file_path: PathLike, block_size: int = _DEFAULT_BLOCK_SIZE) -> str:
    """
    :param file_path: The path to a file to hash
    :param block_size: Number of bytes to read from the file at a time (default: 10MB)
    :return: The hex representation of the given file's sha512 hash
    """
    return _hash_file(sha512, file_path, block_size)
