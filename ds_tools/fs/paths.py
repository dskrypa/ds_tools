"""
:author: Doug Skrypa
"""

from __future__ import annotations

import re
import logging
import os
from datetime import date
from getpass import getuser
from itertools import chain
from pathlib import Path
from stat import S_ISDIR, S_ISREG
from string import printable
from tempfile import gettempdir
from typing import TYPE_CHECKING, Iterator, Iterable, Collection, Mapping, Optional
from urllib.parse import quote

from ..core.decorate import cached_classproperty
from ..core.patterns import FnMatcher

if TYPE_CHECKING:
    from .typing import Paths, PathLike

__all__ = [
    'validate_or_make_dir',
    'get_user_temp_dir',
    'get_user_cache_dir',
    'iter_paths',
    'iter_files',
    'relative_path',
    'iter_sorted_files',
    'unique_path',
    'PathValidator',
    'sanitize_file_name',
    'prepare_path',
    'PathSorter',
    'path_repr',
]
log = logging.getLogger(__name__)

ON_WINDOWS = os.name == 'nt'
_NotSet = object()


# region Walk / Path Iterators


def iter_paths(path_or_paths: Paths) -> Iterator[Path]:
    """
    Convenience function to iterate over Path objects that may be provided as one or more str or Path objects.

    :param path_or_paths: A path or iterable that yields paths
    :return: Generator that yields :class:`Path<pathlib.Path>` objects.
    """
    try:
        win_bash_path_match = iter_paths._win_bash_path_match
    except AttributeError:
        win_bash_path_match = iter_paths._win_bash_path_match = re.compile(r'^/([a-z])/(.*)', re.IGNORECASE).match

    if isinstance(path_or_paths, (str, Path)):
        path_or_paths = (path_or_paths,)

    for p in path_or_paths:
        if isinstance(p, str):
            p = Path(p)
        elif not isinstance(p, Path):
            raise TypeError(f'Unexpected type={p.__class__.__name__} for path={p!r}')

        try:
            if ON_WINDOWS and not p.exists() and (m := win_bash_path_match(p.as_posix())):
                p = Path(f'{m.group(1).upper()}:/{m.group(2)}')
        except OSError:
            if any(c in p.name for c in '*?['):
                matcher = FnMatcher(p.name)
                for root, dirs, files in os.walk(os.getcwd()):
                    root_join = Path(root).joinpath
                    for f in matcher.matching_values(chain(dirs, files)):
                        yield root_join(f)
            else:
                raise
        else:
            yield p.expanduser().resolve()


def iter_files(path_or_paths: Paths, recursive: bool = True) -> Iterator[Path]:
    """
    Iterate over all file paths represented by the given input.  If any directories are provided, they are traversed
    recursively to discover all files within them.

    :param path_or_paths: A path or iterable that yields paths
    :param recursive: If True, provided directories will be traversed recursively, otherwise only the files they
      directly contain will be yielded.
    :return: Generator that yields :class:`Path<pathlib.Path>` objects.
    """
    for path in iter_paths(path_or_paths):
        mode = path.stat().st_mode
        if S_ISREG(mode):  # It is a file
            yield path
        elif S_ISDIR(mode):
            if recursive:
                for root, dirs, files in os.walk(path):
                    if not files:
                        continue
                    root_join = Path(root).joinpath
                    for f in files:
                        yield root_join(f)
            else:
                with os.scandir(path) as scanner:
                    # DirEntry.is_file() generally won't result in a system call, while iterating over Path.iterdir()
                    # and calling Path.is_file() on each result will call stat for each path.
                    for entry in scanner:
                        if entry.is_file():
                            yield Path(entry)


def iter_sorted_files(
    path_or_paths: Paths,
    ignore_dirs: Collection[str] = None,
    ignore_files: Collection[str] = None,
    ignore_suffixes: Collection[str] = None,
    *,
    follow_links: bool = False,
) -> Iterator[Path]:
    """
    Similar to os.walk, but only yields Path objects for files, and traverses the directory tree in sorted order.

    :param path_or_paths: A path or iterable that yields paths
    :param ignore_dirs: Collection of directory names to skip (doesn't support wildcards)
    :param ignore_files: Collection of file names to skip (doesn't support wildcards)
    :param ignore_suffixes: File suffixes to skip (including the preceding ``.``) (doesn't support wildcards)
    :param follow_links: Follow directory symlinks to also yield Path objects from the target of each symlink directory
    :return: Iterator that yields Path objects for the files in the given path or paths, sorted at each level.
    """
    if ignore_dirs and not isinstance(ignore_dirs, set):
        ignore_dirs = set(ignore_dirs)
    if ignore_files and not isinstance(ignore_files, set):
        ignore_files = set(ignore_files)
    if ignore_suffixes and not isinstance(ignore_suffixes, tuple):
        ignore_suffixes = tuple(ignore_suffixes)  # Necessary because DirEntry objects have no .suffix attr

    for path in iter_paths(path_or_paths):
        if path.is_file():
            if (
                (not ignore_files or path.name not in ignore_files)
                and (not ignore_suffixes or path.suffix not in ignore_suffixes)
            ):
                yield path
        # Note: is_file calls stat with follow_symlinks=True, while is_symlink calls stat with follow_symlinks=False
        elif (not ignore_dirs or path.name not in ignore_dirs) and (follow_links or not path.is_symlink()):
            yield from _iter_sorted_files(path, ignore_dirs, ignore_files, ignore_suffixes, follow_links)


def _iter_sorted_files(
    root: Path,
    ignore_dirs: set[str] = None,
    ignore_files: set[str] = None,
    ignore_suffixes: tuple[str, ...] = None,
    follow_links: bool = False,
) -> Iterator[Path]:
    """
    Similar to os.walk, but only yields Path objects for files, and traverses the directory tree in sorted order.

    :param root: The path to walk
    :param ignore_dirs: Collection of directory names to skip (doesn't support wildcards)
    :param ignore_files: Collection of file names to skip (doesn't support wildcards)
    :param ignore_suffixes: File suffixes to skip (including the preceding ``.``) (doesn't support wildcards)
    :param follow_links: Follow directory symlinks to also yield Path objects from the target of each symlink directory
    :return: Iterator that yields Path objects for the files in the given path, sorted at each level.
    """
    dirs = []
    with os.scandir(root) as scanner:
        for entry in sorted(scanner, key=lambda de: de.name):
            if entry.is_dir():
                if (not ignore_dirs or entry.name not in ignore_dirs) and (follow_links or not entry.is_symlink()):
                    dirs.append(root.joinpath(entry.name))
            elif (
                (not ignore_files or entry.name not in ignore_files)
                and (not ignore_suffixes or entry.name.endswith(ignore_suffixes))
            ):
                yield root.joinpath(entry.name)

    for path in dirs:
        yield from _iter_sorted_files(path, ignore_dirs, ignore_files, ignore_suffixes, follow_links)


# endregion


def validate_or_make_dir(
    dir_path: PathLike, permissions: int = None, suppress_perm_change_exc: bool = True
) -> Path:
    """
    Validate that the given path exists and is a directory.  If it does not exist, then create it and any intermediate
    directories.

    Example value for permissions: 0o1777

    :param dir_path: The path of a directory that exists or should be created if it doesn't
    :param permissions: Permissions to set on the directory if it needs to be created (octal notation is suggested)
    :param suppress_perm_change_exc: Suppress an OSError if the permission change is unsuccessful (default:
      suppress/True)
    :return: The path
    """
    path = Path(dir_path).expanduser()
    if path.is_dir():
        return path
    elif path.exists():
        raise ValueError(f'Invalid path - not a directory: {dir_path}')
    else:
        path.mkdir(parents=True)
        if permissions is not None:
            try:
                path.chmod(permissions)
            except OSError as e:
                log.error(f'Error changing permissions of path {dir_path!r} to 0o{permissions:o}: {e}')
                if not suppress_perm_change_exc:
                    raise
    return path


def get_user_cache_dir(subdir: str = None, mode: int = 0o777) -> Path:
    cache_dir = get_user_temp_dir(*filter(None, ('ds_tools_cache', subdir)), mode=mode)
    if not cache_dir.is_dir():
        raise ValueError(f'Invalid path - not a directory: {cache_dir.as_posix()}')
    return cache_dir


def get_user_temp_dir(*sub_dirs, mode: int = 0o777) -> Path:
    """
    On Windows, returns `~/AppData/Local/Temp` or a sub-directory named after the current user of another temporary
    directory.  On Linux, returns a sub-directory named after the current user in `/tmp`, `/var/tmp`, or `/usr/tmp`.

    :param sub_dirs: Child directories of the chosen directory to include/create
    :param mode: Permissions to set if the directory needs to be created (0o777 by default, which matches the default
      for :meth:`pathlib.Path.mkdir`)
    """
    path = Path(gettempdir())
    if not ON_WINDOWS or not path.as_posix().endswith('AppData/Local/Temp'):
        path = path.joinpath(getuser())
    if sub_dirs:
        path = path.joinpath(*sub_dirs)
    if not path.exists():
        path.mkdir(mode=mode, parents=True, exist_ok=True)
    return path


def relative_path(path: PathLike, to: PathLike = '.') -> str:
    path = Path(path).resolve()
    to = Path(to).resolve()
    try:
        return path.relative_to(to).as_posix()
    except Exception:  # noqa
        return path.as_posix()


class _UniquePathPicker:
    __slots__ = ()

    def __call__(
        self,
        parent: Path,
        stem: str,
        suffix: str = '',
        *,
        seps: tuple[str, str] = ('_', '-'),
        n: int = 1,
        add_date: bool = False,
        sanitize: bool = False,
    ) -> Path:
        """
        :param parent: Directory in which a unique file name should be created
        :param stem: File name without extension
        :param suffix: File extension, including `.`
        :param seps: Separators between stem and date/n, respectfully.
        :param n: First number to try; incremented by 1 until adding this value would cause the file name to be unique
        :param add_date: Whether a date should be added before n. If True, a date will always be added.
        :param sanitize: Whether the stem should be sanitized
        :return: Path with a file name that does not currently exist in the target directory
        """
        if sanitize:
            stem = sanitize_file_name(stem)
        date_sep, n_sep = seps
        if add_date:
            stem = f'{stem}{date_sep}{date.today().isoformat()}'
        name = stem + suffix
        while (path := parent.joinpath(name)).exists():
            name = f'{stem}{n_sep}{n}{suffix}'
            n += 1
        return path

    def for_path(
        self,
        path: PathLike,
        *,
        seps: tuple[str, str] = ('_', '-'),
        n: int = 1,
        add_date: bool = False,
        sanitize: bool = False,
    ) -> Path:
        if not isinstance(path, Path):
            path = Path(path).expanduser()
        return self(path.parent, path.stem, path.suffix, seps=seps, n=n, add_date=add_date, sanitize=sanitize)


unique_path = _UniquePathPicker()


class PathValidator:
    _replacements = {'/': '_', ':': '-', '\\': '_', '|': '-'}
    _mac_reserved = {':'}

    def __init__(self, replacements: Optional[Mapping[str, str]] = _NotSet):
        replacements = self._replacements if replacements is _NotSet else {} if replacements is None else replacements
        self.table = str.maketrans({i: replacements.get(i) or quote(i, safe='') for i in self._invalid_chars})  # noqa

    def validate(self, file_name: str):
        root = os.path.splitext(os.path.basename(file_name))[0]
        if root in self._mac_reserved or root in self._win_reserved:
            raise ValueError(f'Invalid {file_name=} - it contains reserved name={root!r}')
        if invalid := next((c for c in self._invalid_chars if c in file_name), None):  # noqa
            raise ValueError(f'Invalid {file_name=} - it contains 1 or more invalid characters, including {invalid!r}')

    def sanitize(self, file_name: str) -> str:
        root = os.path.splitext(os.path.basename(file_name))[0]
        if root in self._mac_reserved or root in self._win_reserved:
            file_name = f'_{file_name}'
        return file_name.translate(self.table)

    @classmethod
    def _sanitize(cls, file_name: str, replacements: Optional[Mapping[str, str]] = _NotSet) -> str:
        return cls(replacements).sanitize(file_name)

    @cached_classproperty
    def _win_reserved(cls) -> set[str]:  # noqa
        reserved = {'CON', 'PRN', 'AUX', 'CLOCK$', 'NUL'}
        reserved.update(f'{n}{i}' for n in ('COM', 'LPT') for i in range(1, 10))
        return reserved

    @cached_classproperty
    def _invalid_chars(cls) -> set[str]:  # noqa
        unprintable_ascii = {c for c in map(chr, range(128)) if c not in printable}
        win_invalid = '/:*?"<>|\t\n\r\x0b\x0c\\'
        return unprintable_ascii.union(win_invalid)


sanitize_file_name = PathValidator._sanitize


def prepare_path(path: PathLike, default_name: tuple[str, str] = None, exist_ok: bool = True, **kwargs) -> Path:
    """
    Convenience function to prepare a file path, creating its parent directory if it does not already exist, and
    optionally generating a file name if a directory is provided and default_name is specified.

    :param path: A path to a file that will be created, or possibly the directory in which to create it
    :param default_name: Tuple of (stem, suffix) to use with :func:`unique_path` to find a unique file name when the
      given path is a directory or has no suffix/extension.
    :param exist_ok: Whether it is okay if the target file exists already. If False, then a ValueError will be raised if
      the final path already exists.
    :param kwargs: Additional keyword arguments to pass to :func:`unique_path`
    :return: The path for a file
    """
    path = Path(path).expanduser()
    if default_name and (path.is_dir() or not path.suffix):
        stem, suffix = default_name
        path = unique_path(path, stem, suffix, **kwargs)
    if not path.parent.exists():
        path.parent.mkdir(parents=True)
    if path.is_dir():
        raise ValueError(f'Invalid file path={path.as_posix()!r} - it is a directory')
    elif not exist_ok and path.exists():
        raise ValueError(f'Invalid file path={path.as_posix()!r} - it already exists')
    return path


class PathSorter:
    __slots__ = ('pattern',)

    def __init__(self):
        self.pattern = re.compile(r'^(\d*)(.*)$')

    def _sort_key(self, path: Path) -> tuple[int, str]:
        if m := self.pattern.match(path.name):
            num_str, remainder = m.groups()
            num = int(num_str) if num_str else 0
            return num, remainder.lower()
        return 0, path.name.lower()

    def sort(self, paths: Iterable[Path], reverse: bool = False) -> list[Path]:
        return sorted(paths, key=self._sort_key, reverse=reverse)

    __call__ = sort

    def sort_list(self, paths: list[Path], reverse: bool = False) -> list[Path]:
        paths.sort(key=self._sort_key, reverse=reverse)
        return paths


def path_repr(path: Path, is_dir: bool = None) -> str:
    path_strs = [path.as_posix()]
    try:
        path_strs.append(f'~/{path.relative_to(Path.home()).as_posix()}')
    except Exception:  # noqa
        pass

    cwd = Path.cwd()
    try:
        path_strs.append(path.relative_to(cwd).as_posix())
    except Exception:  # noqa
        pass
    try:
        path_strs.append(path.resolve().relative_to(cwd.resolve()).as_posix())
    except Exception:  # noqa
        pass

    if is_dir is None:
        try:
            is_dir = path.is_dir()
        except OSError:
            is_dir = False

    path_str = min(path_strs, key=len)
    return (path_str + '/') if is_dir else path_str
