"""
Install a service on FreeBSD via rc.d

:author: Doug Skrypa
"""

import grp  # noqa
import logging
import pwd  # noqa
from abc import ABC, abstractmethod
from pathlib import Path

from ..app_info import AppInfo

__all__ = ['Service']
log = logging.getLogger(__name__)


class AppProperty:
    def __set_name__(self, owner, name):
        self.name = name

    def __get__(self, obj, cls):
        if obj is None:
            return self
        return getattr(obj.app, self.name)


class Service(ABC):
    name = AppProperty()
    user = AppProperty()
    group = AppProperty()

    def __init__(self, app: AppInfo):
        self.app = app

    @abstractmethod
    def env_user_check(self):
        raise NotImplementedError

    # region Config File Creation

    @abstractmethod
    def prepare_service_config(self, **kwargs) -> str:
        raise NotImplementedError

    @abstractmethod
    def get_service_config_path(self) -> Path:
        raise NotImplementedError

    def write_service_config(self, permissions: int = 0o755, overwrite: bool = False, **kwargs):
        path = self.get_service_config_path()
        if path.exists():
            warning = f'Service config path={path.as_posix()} already exists'
            if overwrite:
                log.warning(f'{warning} - overwriting it')
            else:
                raise RuntimeError(warning)

        config = self.prepare_service_config(**kwargs)
        log.info(f'Creating service config: {path.as_posix()}')
        path.write_text(config, encoding='utf-8')
        path.chmod(permissions)

    # endregion

    # region Enable / Start

    @abstractmethod
    def enable(self):
        raise NotImplementedError

    @abstractmethod
    def start(self):
        raise NotImplementedError

    def enable_and_start(self):
        self.enable()
        self.start()

    # endregion

    # region User & Group Creation

    @abstractmethod
    def create_user(self):
        raise NotImplementedError

    @abstractmethod
    def create_group(self):
        raise NotImplementedError

    @abstractmethod
    def add_user_to_group(self):
        raise NotImplementedError

    def ensure_user_exists(self):
        try:
            pwd_user = pwd.getpwnam(self.user)
        except KeyError:
            pass
        else:
            log.info(f'User={self.user!r} already exists')
            return

        self.create_user()

    def ensure_user_is_in_group(self):
        user_struct = pwd.getpwnam(self.user)
        gid = user_struct.pw_gid
        group_struct = grp.getgrgid(gid)
        if group_struct.gr_name == self.group:
            log.info(f'User={self.user!r} is already in group={self.group!r}')
            return

        try:
            group_struct = grp.getgrnam(self.group)
        except KeyError:
            self.create_group()
            group_struct = grp.getgrnam(self.group)

        if self.user not in group_struct.gr_mem:
            self.add_user_to_group()

    # endregion
