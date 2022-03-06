"""
Archive extraction utilities

.. warning:
    Not intended to handle any files with sensitive passwords - this is intended to decompress files with perfunctory
    passwords in bulk.  Passwords WILL BE PRINTED and stored very insecurely if you choose to save them.  Do not use
    with any passwords that are sensitive.

:author: Doug Skrypa
"""

import logging
import os
import shutil
from abc import ABC, abstractmethod
from bz2 import BZ2File
from functools import cached_property
from gzip import GzipFile
from lzma import LZMAFile, LZMAError
from pathlib import Path
from tarfile import TarFile
from tempfile import TemporaryDirectory
from typing import Union, Optional, Iterable, Iterator, Type, TypeVar
from weakref import finalize
from zipfile import ZipFile

from py7zr import SevenZipFile, PasswordRequired
from rarfile import RarFile, BadRarFile, ToolSetup

from ..input.prompts import get_input
from .exceptions import InvalidPassword, UnknownArchiveType

__all__ = ['ArchiveFile']
log = logging.getLogger(__name__)
ArchiveFileType = TypeVar('ArchiveFileType', bound='ArchiveFile')

_WINDOWS = os.name == 'nt'


class ArchiveFile(ABC):
    _ext_cls_map: dict[str, ArchiveFileType] = {}
    _exts: tuple[str, ...] = None
    _cls: Type = None

    def __init_subclass__(cls: ArchiveFileType, fcls: Type = None, ext: str = None, exts: Iterable[str] = None):
        if fcls is None and ABC not in cls.__bases__:
            raise ValueError(f'ArchiveFile subclass {cls.__name__} must specify fcls')
        elif ((not ext and not exts) or (ext and exts)) and ABC not in cls.__bases__:
            raise ValueError(f'ArchiveFile subclass {cls.__name__} must specify either ext or exts, not both')
        elif ext:
            cls._exts = (ext,)
            cls._ext_cls_map[ext.lower()] = cls
        elif exts:
            cls._exts = tuple(exts)
            for ext in exts:
                cls._ext_cls_map[ext.lower()] = cls

        cls._cls = fcls

    def __new__(cls, path: Union[str, Path]) -> ArchiveFileType:
        if cls is ArchiveFile:
            cls = cls.class_for(path)
        return super().__new__(cls)

    def __init__(self, path: Union[str, Path], use_arc_name: bool = False):
        self.use_arc_name = use_arc_name
        self.path = Path(path).expanduser().resolve()
        lc_name = self.path.name.lower()
        self.ext = next(('.' + ext for ext in self._exts if lc_name.endswith(ext)), None)
        self.stem = self.path.name[:-len(self.ext)] if self.ext else self.path.name
        self._finalizer = finalize(self, self._close)

    def __repr__(self) -> str:
        return f'<{self.__class__.__name__}({self.path.as_posix()!r})>'

    @classmethod
    def class_for(cls, path: Union[str, Path]) -> Type[ArchiveFileType]:
        ext = full_ext = ''.join(Path(path).suffixes)[1:].lower()
        while not (sub_cls := cls._ext_cls_map.get(ext)):
            if '.' in ext:
                ext = ext.split('.', 1)[1]
            else:
                break
        if sub_cls is None:
            raise UnknownArchiveType(full_ext, path) from None
        return sub_cls

    @classmethod
    def is_archive(cls, path: Union[str, Path]) -> bool:
        try:
            cls.class_for(path)
        except UnknownArchiveType:
            return False
        else:
            return True

    def extract_all(self, dst_root: Union[str, Path] = None) -> Optional[Path]:
        dst_root = _prepare_destination(dst_root)
        if self.needs_password:
            return self._extract_all_with_pw(dst_root)
        else:
            log.debug(f'Extracting {self.path.as_posix()} with no password...')
            result = self._try_extract(dst_root)
            log.debug(f'Successfully extracted {self.path.as_posix()} with no password')
            return result

    def _extract_all_with_pw(self, dst_root: Path) -> Optional[Path]:
        passwords = Passwords()
        log.debug(f'Extracting {self.path.as_posix()} - trying {len(passwords)} known passwords...')
        for i, password in enumerate(passwords):
            try:
                result = self._try_extract(dst_root, password, i, len(passwords))
            except InvalidPassword:
                pass
            else:
                log.debug(f'Successfully extracted {self.path.as_posix()} using {password=!r}')
                return result
        else:
            log.debug(f'Extracting {self.path.as_posix()} - requesting new password(s)...')
            while password := passwords.get_new(f'Enter new password for {self.path.as_posix()}:'):
                try:
                    result = self._try_extract(dst_root, password)
                except InvalidPassword:
                    passwords.remove(password)
                else:
                    log.debug(f'Successfully extracted {self.path.as_posix()} using {password=!r}')
                    passwords.add(password)  # .add will prompt to save or not
                    return result

        return None

    def _try_extract(self, dst_root: Path, password: str = None, pw_n: int = None, pw_count: int = None) -> Path:
        with TemporaryDirectory(dir=dst_root) as tmp_dir:
            log.debug(f'Trying to extract {self.path.as_posix()} to tmp={tmp_dir}')
            try:
                self._extract_all(tmp_dir, password, pw_n, pw_count)
            except InvalidPassword as e:
                log.debug(e)
                raise
            else:
                tmp_dir_path = Path(tmp_dir)
                if not self.use_arc_name and len(content := list(tmp_dir_path.iterdir())) == 1 and content[0].is_dir():
                    extracted = content[0]
                    dst_path = dst_root.joinpath(extracted.name)
                    if not dst_path.exists():
                        log.debug(f'Renaming extracted dir={extracted.as_posix()} -> {dst_path.as_posix()}')
                        extracted.rename(dst_path)
                        return dst_path
                    else:
                        log.debug(f'Destination={dst_path.as_posix()} already existed')
                    # else fall back to using arc name

                dst_path = _prep_extracted_dest(dst_root, self.stem)
                log.debug(f'Renaming tmp={tmp_dir_path.as_posix()} -> {dst_path.as_posix()}')
                tmp_dir_path.rename(dst_path)
                return dst_path

    @cached_property
    def file(self):
        return self._cls(self.path)

    def _close(self):
        if 'file' in self.__dict__ and (file := self.file) is not None:
            file.close()  # noqa
            self.__dict__['file'] = None

    def close(self):
        if self._finalizer.detach():
            self._close()

    @abstractmethod
    def _extract_all(self, path: Union[Path, str], password: str = None, pw_n: int = None, pw_count: int = None):
        raise NotImplementedError

    @property
    @abstractmethod
    def needs_password(self):
        raise NotImplementedError


# region Multi-File Archives


class RarArchiveFile(ArchiveFile, fcls=RarFile, ext='rar'):
    def __init__(self, path: Union[str, Path]):
        super().__init__(path)
        patch_rarfile()

    @property
    def needs_password(self):
        return self.file.needs_password()

    def _extract_all(self, path: Union[Path, str], password: str = None, pw_n: int = None, pw_count: int = None):
        if password:
            self.file.setpassword(password)  # Needs to be set first when names are encrypted or nothing is extracted
        try:
            self.file.extractall(path)
        except BadRarFile as e:
            if password:
                raise InvalidPassword(self, e, password, pw_n, pw_count) from e
            raise


class SevenZipArchiveFile(ArchiveFile, fcls=SevenZipFile, ext='7z'):
    _pw_required = None

    @cached_property
    def file(self):
        try:
            file = SevenZipFile(self.path)
        except PasswordRequired:
            self._pw_required = True
            return None
        else:
            self._pw_required = False
            return file

    @property
    def needs_password(self):
        if self._pw_required is None and (file := self.file):
            self._pw_required = file.needs_password()  # noqa
            if self._pw_required:
                file.close()
                self.__dict__['file'] = None
        return self._pw_required

    def _extract_all(self, path: Union[Path, str], password: str = None, pw_n: int = None, pw_count: int = None):
        file = SevenZipFile(self.path, password=password) if password else self.file
        try:
            with file:
                file.extractall(path)
        except LZMAError as e:
            if password:
                raise InvalidPassword(self, e, password, pw_n, pw_count) from e
            raise
        finally:
            self.__dict__['file'] = None


class TarArchiveFile(ArchiveFile, fcls=TarFile, exts=('tar', 'tgz', 'tar.gz', 'tbz2', 'tar.bz2', 'txz', 'tar.xz')):
    @cached_property
    def file(self):
        return TarFile.open(self.path)

    @property
    def needs_password(self):
        return False

    def _extract_all(self, path: Union[Path, str], password: str = None, pw_n: int = None, pw_count: int = None):
        self.file.extractall(path)


class ZipArchiveFile(ArchiveFile, fcls=ZipFile, ext='zip'):
    @property
    def needs_password(self):
        return any(file.flag_bits & 0x1 for file in self.file.filelist)

    def _extract_all(self, path: Union[Path, str], password: str = None, pw_n: int = None, pw_count: int = None):
        try:
            self.file.extractall(path, pwd=password.encode('utf-8') if password else None)
        except RuntimeError as e:
            if password and e.args[0].lower().startswith('bad password'):
                raise InvalidPassword(self, e, password, pw_n, pw_count) from e
            raise


# endregion

# region Single-File Archives


class _SingleArchiveFile(ArchiveFile, ABC):
    @property
    def needs_password(self):
        return False

    def _extract_all(self, path: Union[Path, str], password: str = None, pw_n: int = None, pw_count: int = None):
        raise NotImplementedError

    def extract_all(self, dst_root: Union[str, Path] = None):
        dst_root = _prepare_destination(dst_root)
        dst_path = dst_root.joinpath(self.stem)
        log.info(f'Extracting {self.path.as_posix()} -> {dst_path.as_posix()}')
        with self.file as f_in, dst_path.open('wb') as f_out:
            shutil.copyfileobj(f_in, f_out)


class LzmaArchiveFile(_SingleArchiveFile, fcls=LZMAFile, ext='xz'):
    pass


class GzipArchiveFile(_SingleArchiveFile, fcls=GzipFile, ext='gz'):
    pass


class BZ2ArchiveFile(_SingleArchiveFile, fcls=BZ2File, ext='bz2'):
    pass


# endregion


class Passwords:
    """
    Passwords to try for extracting archive contents.

    Saved passwords are store insecurely in ``~/.config/ds_tools_archives/archive_passwords.txt`` - they should only be
    stored if they are not really secret / important.
    """
    __instance = None
    path = Path('~/.config/ds_tools_archives/archive_passwords.txt').expanduser()

    def __new__(cls, *args, **kwargs):
        if cls.__instance is None:
            cls.__instance = super().__new__(cls)
        return cls.__instance

    def __init__(self):
        if not hasattr(self, '_passwords'):
            self._passwords = None
            self._temp_passwords = set()
            self._last_read = 0
            if not self.path.parent.exists():
                self.path.parent.mkdir(parents=True)

    def _read(self) -> set[str]:
        if self.path.exists():
            self._last_read = self.path.stat().st_mtime
            with self.path.open('r', encoding='utf-8') as f:
                return set(filter(None, map(str.strip, f)))
        return set()

    def _save(self, passwords: set[str]):
        log.debug(f'Saving changes to {self.path.as_posix()}')
        with self.path.open('w', encoding='utf-8') as f:
            f.write('\n'.join(passwords))

    @property
    def passwords(self):
        if not self.path.exists():
            self.path.touch()
        if self.path.stat().st_mtime > self._last_read:
            self._passwords = self._read()
        return self._passwords

    @property
    def all_passwords(self):
        return self.passwords.union(self._temp_passwords)

    def get_new(self, prompt: str) -> Optional[str]:
        suffix = ' ' if not prompt.endswith(' ') else ''
        try:
            user_input = input(prompt + suffix)
        except EOFError:
            return None

        if user_input:
            self._temp_passwords.add(user_input)
        #     self.add(user_input)
        return user_input

    def add(self, password: str):
        if password not in self.passwords:
            if get_input(f'Store {password=!r} in {self.path.as_posix()} ?'):
                passwords = self.passwords
                passwords.add(password)
                self._save(passwords)
            # else:
            #     self._temp_passwords.add(password)

    def remove(self, password: str):
        self._temp_passwords.discard(password)
        passwords = self.passwords
        try:
            passwords.remove(password)
        except KeyError:
            pass
        else:
            self._save(passwords)

    def __len__(self) -> int:
        return len(self.all_passwords)

    def __iter__(self) -> Iterator[str]:
        yield from self.all_passwords


def _prepare_destination(dst_root: Union[str, Path] = None) -> Path:
    dst_root = Path(dst_root).expanduser().resolve() if dst_root else Path.cwd()
    if dst_root.exists() and not dst_root.is_dir():
        raise ValueError(f'Invalid dst_root={dst_root.as_posix()!r} - it must be a directory')
    elif not dst_root.exists():
        dst_root.mkdir(parents=True)
    return dst_root


def _prep_extracted_dest(dst_root: Path, name: str) -> Path:
    dst_path = dst_root.joinpath(name)
    if not dst_path.exists():
        return dst_path

    i = 1
    while dst_path.exists():
        dst_path = dst_root.joinpath(f'{name}-{i}')

    return dst_path


def patch_rarfile():
    # Patch ToolSetup.add_file_arg to provide paths in a way that UnRAR understands
    try:
        applied = patch_rarfile._applied
    except AttributeError:
        applied = False

    if _WINDOWS and not applied:
        def add_file_arg(self, cmdline, filename):
            file_name = filename.replace('/', '\\')
            cmdline.append(file_name)

        ToolSetup.add_file_arg = add_file_arg

    patch_rarfile._applied = True
