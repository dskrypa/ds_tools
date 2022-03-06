"""
Exceptions for the ds_tools.fs package

:author: Doug Skrypa
"""

from typing import TYPE_CHECKING, Union

if TYPE_CHECKING:
    from pathlib import Path
    from .archives import ArchiveFile


class InvalidPathError(Exception):
    """Exception to be raised when a given path cannot be handled"""


class InvalidPassword(Exception):
    """Exception to be raised when an invalid archive password is provided"""
    def __init__(
        self, archive: 'ArchiveFile', e: Exception, password: str = None, pw_n: int = None, pw_count: int = None
    ):
        self.archive = archive
        self.e = e
        self.password = password
        self.pw_n = pw_n
        self.pw_count = pw_count

    def __str__(self):
        pw_n, pw_count = self.pw_n, self.pw_count
        pw_info = f' ({pw_n} / {pw_count})' if pw_n and pw_count else f' ({pw_n})' if pw_n else ''
        return f'Failed to extract {self.archive.path.as_posix()} using {self.password=!r}{pw_info}: {self.e}'


class UnknownArchiveType(ValueError):
    """Exception to be raised when a given archive has an unexpected file extension"""
    def __init__(self, ext: str, path: Union[str, 'Path']):
        self.ext = ext
        self.path = path

    def __str__(self) -> str:
        return f'Unknown archive extension={self.ext!r} for path={self.path!r}'
