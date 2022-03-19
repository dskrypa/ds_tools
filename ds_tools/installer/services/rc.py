"""
Install a service on FreeBSD via rc.d

:author: Doug Skrypa
"""

import logging
import os
from pathlib import Path
from subprocess import check_call

from ..app_info import AppInfo
from .base import Service

__all__ = ['RcService']
log = logging.getLogger(__name__)


SERVICE_SCRIPT_TEMPLATE = r"""#!/bin/sh

# PROVIDE: {name}
# REQUIRE: LOGIN
# KEYWORD: shutdown

# Add the following lines to /etc/rc.conf to enable {name}
# {name}_enable="YES"
#
# {name}_enable (bool):
#     Set it to YES to enable {name}
#     Set to NO by default
# {name}_user (string):
#     Set user that {name} will run under
#     Default is "{user}"
# {name}_group (string):
#     Set group that own {name} files
#     Default is "{group}"

. /etc/rc.subr

name={name}
rcvar={name}_enable

load_rc_config $name

: ${{{name}_enable:="NO"}}
: ${{{name}_user:="{user}"}}
: ${{{name}_group:="{group}"}}

pidfile="/var/run/${{name}}/${{name}}.pid"
procname="{bin_path}"
command="/usr/sbin/daemon"
command_args="-f -T ${{name}} -p ${{pidfile}} -t ${{name}} \
            /usr/bin/env ${{{name}_env}} \
            ${{procname}} {cmd_args_tmpl}"

start_precmd="{name}_start_precmd"

{name}_start_precmd() {{
    if [ ! -d "/var/run/${{name}}" ]; then
        install -d -m 0750 -o ${{{name}_user}} -g ${{{name}_group}} "/var/run/${{name}}"
    fi
}}

run_rc_command "$1"
"""


class RcService(Service):
    def __init__(self, app: AppInfo):
        super().__init__(app=app)

    def env_user_check(self):
        rc_d_dir = Path('/usr/local/etc/rc.d')
        if not rc_d_dir.exists():
            raise RuntimeError(f'Could not find {rc_d_dir.as_posix()} - {self.name} only supports setup via rc')

        rc_d_dir_stat = rc_d_dir.stat()
        if rc_d_dir_stat.st_uid != os.getuid() or rc_d_dir_stat.st_gid != os.getgid():  # noqa
            raise RuntimeError(f'You must run `sudo {self.name}` to proceed')

    # region Config File Creation

    def prepare_service_config(self, **kwargs) -> str:
        return SERVICE_SCRIPT_TEMPLATE.format(
            name=self.name,
            user=self.user,
            group=self.group,
            bin_path=self.app.bin_path,
            cmd_args_tmpl=self.app.cmd_args,
            **kwargs,
        )

    def get_service_config_path(self) -> Path:
        return Path('/usr/local/etc/rc.d', self.name)

    # endregion

    # region Enable / Start

    def enable(self):
        log.info(f'Enabling service={self.app.name}')
        check_call(['sysrc', f'{self.name}_enable=YES'])

    def start(self):
        log.info(f'Starting service={self.app.name}')
        check_call(['service', self.name, 'start'])

    # endregion

    # region User & Group Creation

    def create_user(self):
        log.info(f'Creating user={self.user!r}')
        check_call(['pw', 'user', 'add', self.user])

    def create_group(self):
        log.info(f'Creating group={self.group!r}')
        check_call(['pw', 'group', 'add', self.group])

    def add_user_to_group(self):
        log.info(f'Adding user={self.user!r} to group={self.group!r}')
        check_call(['pw', 'user', 'mod', self.user, '-G', self.group])

    # endregion
