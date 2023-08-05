"""
File System Mount Info
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

from psutil import disk_partitions
from psutil._common import sdiskpart, get_procfs_path

from .exceptions import InvalidPathError

if TYPE_CHECKING:
    from .typing import PathLike

__all__ = ['get_disk_partition', 'is_on_local_device', 'on_same_fs']

ON_WINDOWS = os.name == 'nt'


def get_disk_partition(path: PathLike) -> sdiskpart:
    return DiskMountPartitionMapper().get_disk_partition(path)


class DiskMountPartitionMapper:
    __slots__ = ('partitions',)

    def __init__(self):
        self.partitions = {Path(p.mountpoint).resolve(): p for p in disk_partitions(all=True)}

    def get_disk_partition(self, path: PathLike) -> sdiskpart:
        path = orig_path = (Path(path) if not isinstance(path, Path) else path).expanduser().resolve()
        last = None
        while (path := path.parent) != last:
            try:
                return self.partitions[path]
            except KeyError:
                last = path
        raise InvalidPathError(orig_path)


def get_dev_fs_types() -> set[str]:
    """
    [Linux only] The set of filesystem types supported by this system that can only me mounted for block devices.
    Based on code in psutil.disk_partitions.
    """
    fs_types = set()
    procfs_path = get_procfs_path()  # typically /proc
    with open(procfs_path + '/filesystems', 'r', encoding='utf-8') as f:
        for line in map(str.strip, f):
            if not line.startswith('nodev'):
                # nodev indicates the fs type isn't associated with / doesn't require a block device to be mounted
                fs_types.add(line)
            elif line.split('\t', 1)[1] == 'zfs':
                fs_types.add('zfs')
    return fs_types


def is_on_local_device(path: PathLike) -> bool:
    if ON_WINDOWS:
        path = (Path(path) if not isinstance(path, Path) else path).expanduser().resolve()
        return not path.drive.startswith(r'\\')

    try:
        dev_fs_types = is_on_local_device._dev_fs_types
    except AttributeError:
        dev_fs_types = is_on_local_device._dev_fs_types = get_dev_fs_types()

    # TODO: This may not always be entirely accurate... there must be a better way...
    return get_disk_partition(path).fstype in dev_fs_types


def on_same_fs(path_a: PathLike, path_b: PathLike) -> bool:
    """
    Determines whether the given paths are on the same file system.  On Windows, this is determined by examining
    whether the resolved paths' drive prefixes (letter or UNC path) match.  On other OSes, this is determined by
    mapping the resolved paths to the disk partition associated with their mount points and comparing the results.

    :param path_a: A Path or Path-like object
    :param path_b: Another Path or Path-like object
    :return: True if both paths are on the same file system, False otherwise
    """
    if ON_WINDOWS:
        # For network locations, after calling `Path.resolve()`, the `Path.drive` attribute provides the root
        # UNC path (//server/share) instead of a letter with a `:`.  This happens regardless of whether the share is
        # mounted with a drive letter, and regardless of whether the input path used that drive letter or was already
        # in the UNC path format.
        path_a = (Path(path_a) if not isinstance(path_a, Path) else path_a).expanduser().resolve()
        path_b = (Path(path_b) if not isinstance(path_b, Path) else path_b).expanduser().resolve()
        return path_a.drive == path_b.drive
    else:
        get_partition = DiskMountPartitionMapper().get_disk_partition
        return get_partition(path_a) == get_partition(path_b)
