"""
:author: Doug Skrypa
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from psutil import disk_partitions
from psutil._common import sdiskpart, get_procfs_path

from .exceptions import InvalidPathError

if TYPE_CHECKING:
    from .typing import PathLike

__all__ = ['get_disk_partition', 'is_on_local_device']


def get_disk_partition(path: PathLike) -> sdiskpart:
    path = orig_path = Path(path).expanduser().resolve()
    partitions = {p.mountpoint: p for p in disk_partitions(all=True)}
    while path != path.parent:
        try:
            return partitions[path.as_posix()]
        except KeyError:
            path = path.parent

    try:
        return partitions[path.as_posix()]
    except KeyError:
        pass

    raise InvalidPathError(orig_path)


def get_dev_fs_types():
    """Based on code in psutil.disk_partitions"""
    fs_types = set()
    procfs_path = get_procfs_path()
    with open(procfs_path + '/filesystems', 'r', encoding='utf-8') as f:
        for line in map(str.strip, f):
            if not line.startswith('nodev'):
                fs_types.add(line)
            elif line.split('\t', 1)[1] == 'zfs':
                fs_types.add('zfs')
    return fs_types


def is_on_local_device(path: PathLike) -> bool:
    try:
        dev_fs_types = is_on_local_device._dev_fs_types
    except AttributeError:
        dev_fs_types = is_on_local_device._dev_fs_types = get_dev_fs_types()

    return get_disk_partition(path).fstype in dev_fs_types
