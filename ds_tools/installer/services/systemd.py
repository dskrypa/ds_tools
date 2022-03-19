"""
Install a service on Linux via systemd

:author: Doug Skrypa
"""

import logging
import os
from pathlib import Path
from subprocess import check_call

from ..app_info import AppInfo
from .base import Service

__all__ = ['SystemdService']
log = logging.getLogger(__name__)


class SystemdService(Service):
    def __init__(self, app: AppInfo):
        super().__init__(app=app)

    def env_user_check(self):
        systemd_dir = Path('/etc/systemd/system')
        if not systemd_dir.exists():
            raise RuntimeError(f'Could not find {systemd_dir.as_posix()} - {self.name} only supports systemd')

        systemd_dir_stat = systemd_dir.stat()
        if systemd_dir_stat.st_uid != os.getuid() or systemd_dir_stat.st_gid != os.getgid():  # noqa
            raise RuntimeError(f'You must run `sudo {self.name}` to proceed')

    # region Config File Creation

    def prepare_service_config(self) -> str:
        return self.app.get_unit_file().format()

    def get_service_config_path(self) -> Path:
        return Path(f'/etc/systemd/system/{self.name}.service')

    # endregion

    # region Enable / Start

    def enable(self):
        log.info(f'Enabling service={self.name} to run at boot')
        check_call(['systemctl', 'enable', self.name])

    def start(self):
        log.info(f'Starting service={self.name}')
        check_call(['systemctl', 'start', self.name])
        log.info(f'\n\nRun `sudo reboot` to reboot and ensure installation was successful')

    # endregion

    # region User & Group Creation

    def create_user(self):
        log.info(f'Creating user={self.user!r}')
        check_call(['useradd', self.user])

    def create_group(self):
        log.info(f'Creating group={self.group!r}')
        check_call(['groupadd', self.group])

    def add_user_to_group(self):
        log.info(f'Adding user={self.user!r} to group={self.group!r}')
        check_call(['usermod', self.user, '-G', self.group])

    # endregion
