"""
:author: Doug Skrypa
"""

import logging
import os
from itertools import chain
from pathlib import Path
from platform import system
from typing import Iterator, Union, Iterable, Optional, Collection, Set

from ..core.patterns import FnMatcher

__all__ = [
    'validate_or_make_dir',
    'get_user_cache_dir',
    'iter_paths',
    'iter_files',
    'Paths',
    'relative_path',
    'iter_sorted_files',
]
log = logging.getLogger(__name__)
Paths = Union[str, Path, Iterable[Union[str, Path]]]


def iter_paths(path_or_paths: Paths) -> Iterator[Path]:
    """
    Convenience function to iterate over Path objects that may be provided as one or more str or Path objects.

    :param path_or_paths: A path or iterable that yields paths
    :return: Generator that yields :class:`Path<pathlib.Path>` objects.
    """
    try:
        win_bash_path_match = iter_paths._win_bash_path_match
    except AttributeError:
        import re
        win_bash_path_match = iter_paths._win_bash_path_match = re.compile(r'^/([a-z])/(.*)', re.IGNORECASE).match

    if isinstance(path_or_paths, (str, Path)):
        path_or_paths = (path_or_paths,)

    on_windows = system().lower() == 'windows'
    for p in path_or_paths:
        if isinstance(p, str):
            p = Path(p)
        if isinstance(p, Path):
            try:
                if on_windows and not p.exists():
                    if m := win_bash_path_match(p.as_posix()):
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


def iter_sorted_files(
    path_or_paths: Paths,
    ignore_dirs: Optional[Collection[str]] = None,
    ignore_files: Optional[Collection[str]] = None,
    follow_links: bool = False,
) -> Iterator[Path]:
    """
    Similar to os.walk, but only yields Path objects for files, and traverses the directory tree in sorted order.

    :param path_or_paths: A path or iterable that yields paths
    :param ignore_dirs: Collection of directory names to skip (does not support wildcards)
    :param ignore_files: Collection of file names to skip (does not support wildcards)
    :param follow_links: Follow directory symlinks to also yield Path objects from the target of each symlink directory
    :return: Iterator that yields Path objects for the files in the given path or paths, sorted at each level.
    """
    ignore_dirs = set(ignore_dirs) if ignore_dirs and not isinstance(ignore_dirs, set) else None
    ignore_files = set(ignore_files) if ignore_files and not isinstance(ignore_files, set) else None
    for path in iter_paths(path_or_paths):
        if path.is_file():
            if not ignore_files or path.name not in ignore_files:
                yield path
        else:
            if (not ignore_dirs or path.name not in ignore_dirs) and (follow_links or not path.is_symlink()):
                yield from _iter_sorted_files(path, ignore_dirs, ignore_files, follow_links)


def _iter_sorted_files(
    root: Path,
    ignore_dirs: Optional[Set[str]] = None,
    ignore_files: Optional[Set[str]] = None,
    follow_links: bool = False,
) -> Iterator[Path]:
    """
    Similar to os.walk, but only yields Path objects for files, and traverses the directory tree in sorted order.

    :param root: The path to walk
    :param ignore_dirs: Collection of directory names to skip (does not support wildcards)
    :param ignore_files: Collection of file names to skip (does not support wildcards)
    :param follow_links: Follow directory symlinks to also yield Path objects from the target of each symlink directory
    :return: Iterator that yields Path objects for the files in the given path, sorted at each level.
    """
    dirs = []
    for entry in sorted(os.listdir(root)):
        path = root.joinpath(entry)
        if path.is_dir():
            if (not ignore_dirs or entry not in ignore_dirs) and (follow_links or not path.is_symlink()):
                dirs.append(path)
        else:
            if not ignore_files or entry not in ignore_files:
                yield path

    for path in dirs:
        yield from _iter_sorted_files(path, ignore_dirs, ignore_files, follow_links)


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
    from getpass import getuser
    cache_dir = os.path.join('C:/var/tmp' if system().lower() == 'windows' else '/var/tmp', getuser(), 'ds_tools_cache')
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
