"""
:author: Doug Skrypa
"""

import logging
import os
import platform
import re
from getpass import getuser
from itertools import chain
from pathlib import Path
from typing import Iterator, Union, Iterable

from ..core.patterns import FnMatcher

__all__ = ['validate_or_make_dir', 'get_user_cache_dir', 'iter_paths', 'iter_files', 'Paths', 'relative_path']
log = logging.getLogger(__name__)

ON_WINDOWS = platform.system().lower() == 'windows'
WIN_BASH_PATH_MATCH = re.compile(r'^/([a-z])/(.*)', re.IGNORECASE).match

Paths = Union[str, Path, Iterable[Union[str, Path]]]


def iter_paths(path_or_paths: Paths) -> Iterator[Path]:
    """
    Convenience function to iterate over Path objects that may be provided as one or more str or Path objects.

    :param path_or_paths: A path or iterable that yields paths
    :return: Generator that yields :class:`Path<pathlib.Path>` objects.
    """
    if isinstance(path_or_paths, (str, Path)):
        path_or_paths = (path_or_paths,)

    for p in path_or_paths:
        if isinstance(p, str):
            p = Path(p)
        if isinstance(p, Path):
            try:
                if ON_WINDOWS and not p.exists():
                    if m := WIN_BASH_PATH_MATCH(p.as_posix()):
                        p = Path(f'{m.group(1).upper()}:/{m.group(2)}')
            except OSError:
                if any(c in p.name for c in '*?['):
                    matcher = FnMatcher(p.name)
                    for root, dirs, files in os.walk(os.getcwd()):
                        root_path = Path(root)
                        for f in matcher.matching_values(chain(dirs, files)):
                            yield root_path.joinpath(f)
                else:
                    raise
            else:
                yield p.expanduser().resolve()
        else:
            raise TypeError(f'Unexpected type={p.__class__.__name__} for path={p!r}')


def iter_files(path_or_paths: Paths) -> Iterator[Path]:
    """
    Iterate over all file paths represented by the given input.  If any directories are provided, they are traversed
    recursively to discover all files within them.

    :param path_or_paths: A path or iterable that yields paths
    :return: Generator that yields :class:`Path<pathlib.Path>` objects.
    """
    for path in iter_paths(path_or_paths):
        if path.is_file():
            yield path
        else:
            # noinspection PyTypeChecker
            for root, dirs, files in os.walk(path):
                root_path = Path(root)
                for f in files:
                    yield root_path.joinpath(f)


def validate_or_make_dir(dir_path, permissions=None, suppress_perm_change_exc=True):
    """
    Validate that the given path exists and is a directory.  If it does not exist, then create it and any intermediate
    directories.

    Example value for permissions: 0o1777

    :param str dir_path: The path of a directory that exists or should be created if it doesn't
    :param int permissions: Permissions to set on the directory if it needs to be created (octal notation is suggested)
    :param bool suppress_perm_change_exc: Suppress an OSError if the permission change is unsuccessful (default: suppress/True)
    :return str: The path
    """
    if os.path.exists(dir_path):
        if not os.path.isdir(dir_path):
            raise ValueError('Invalid path - not a directory: {}'.format(dir_path))
    else:
        os.makedirs(dir_path)
        if permissions is not None:
            try:
                os.chmod(dir_path, permissions)
            except OSError as e:
                log.error('Error changing permissions of path {!r} to 0o{:o}: {}'.format(dir_path, permissions, e))
                if not suppress_perm_change_exc:
                    raise e
    return dir_path


def get_user_cache_dir(subdir=None, permissions=None):
    cache_dir = os.path.join('C:/var/tmp' if ON_WINDOWS else '/var/tmp', getuser(), 'ds_tools_cache')
    if subdir:
        cache_dir = os.path.join(cache_dir, subdir)
    validate_or_make_dir(cache_dir, permissions=permissions)
    return cache_dir


def relative_path(path: Union[str, Path], to: Union[str, Path] = '.') -> str:
    path = Path(path).resolve()
    to = Path(to).resolve()
    try:
        return path.relative_to(to).as_posix()
    except Exception:
        return path.as_posix()
