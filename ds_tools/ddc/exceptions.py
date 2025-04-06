"""
Exceptions for VCP errors.

:author: Doug Skrypa
"""

from __future__ import annotations

from functools import cached_property
from getpass import getuser
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ['VCPError', 'VCPPermissionError', 'VCPIOError']


class VCPError(Exception):
    """Base VCP exception"""


class VCPPermissionError(VCPError):
    """Error due to insufficient permissions"""

    def __init__(self, path: Path):
        self.path = path

    @cached_property
    def _suggestions(self) -> str:
        try:
            stat = self.path.stat()
        except OSError:
            return ''

        if stat.st_gid == 0:  # the owning group is the root group
            return (
                ' - it is owned by the root group - if you `sudo apt install ddcutil`, it will be updated so that it'
                ' is owned by the `i2c` group instead (alternatively, you may be able to simply `sudo chown ...` it)'
            )

        name = _get_group_name(stat.st_gid)
        desc = f'group={name!r}' if name else f'the group with gid={stat.st_gid}'
        return (
            f' - it is owned by {desc}, but you are not a member'
            f' - you can become a member by running `sudo usermod -a -G {name or stat.st_gid} {getuser()}`,'
            f' followed by `newgrp {name or stat.st_gid}` to log in to it without restarting'
        )

    def __str__(self) -> str:
        return f'Permission error for {self.path}{self._suggestions}'


def _get_group_name(gid: int) -> str | None:
    try:
        from grp import getgrgid

        return getgrgid(gid).gr_name
    except (ImportError, KeyError):  # Neither error is expected
        return None


class VCPIOError(VCPError):
    """Error during IO operations"""
