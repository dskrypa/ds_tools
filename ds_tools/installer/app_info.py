"""
Base app info template

:author: Doug Skrypa
"""

import platform
from dataclasses import dataclass, field, fields
try:
    from typing import Sequence, Literal, Optional
except ImportError:
    from typing import Sequence, Optional

    class Literal:
        def __class_getitem__(cls, item):
            return None


@dataclass
class AppInfo:
    name: str
    user: str
    group: str
    bin_path_tmpl: str
    cmd_args: str = None
    description: str = None
    unit_file: Optional['UnitFile'] = None
    rc_config: Optional['RcConfig'] = None

    @property
    def bin_path(self) -> str:
        uname = platform.uname()
        system = uname.system.lower()
        machine = uname.machine.lower()
        if machine.startswith('arm'):
            bits = int(platform.architecture()[0][:2])
            arch = 'arm' if bits == 32 else f'arm{bits}'
        else:
            arch = machine
        return self.bin_path_tmpl.format(system=system, arch=arch)

    def get_unit_file(self) -> 'UnitFile':
        unit_file = self.unit_file or UnitFile()
        if self.description is not None and unit_file.unit.description is None:
            unit_file.unit.description = self.description

        service = unit_file.service
        if service.exec_start is None:
            cmd_parts = [self.bin_path]
            if self.cmd_args:
                cmd_parts.append(self.cmd_args)
            service.exec_start = ' '.join(cmd_parts)
        if service.user is None:
            service.user = self.user

        return unit_file

    def get_rc_config(self) -> 'RcConfig':
        rc_config = self.rc_config or RcConfig()
        return rc_config


# region Unit File

class UnitFileSection:
    def format(self):
        parts = [f'[{self.__class__.__name__}]']
        for f in fields(self):
            key = f.name
            value = getattr(self, key)
            if value is not None:
                key = snake_to_pascal_case(key)
                if isinstance(value, Sequence) and not isinstance(value, str):
                    value = ' '.join(value)
                parts.append(f'{key}={value}')
        return '\n'.join(parts)


@dataclass
class Unit(UnitFileSection):
    description: str = None
    documentation: str = None
    requires: Sequence[str] = None
    wants: Sequence[str] = None
    binds_to: Sequence[str] = None
    before: Sequence[str] = None
    after: Sequence[str] = ('multi-user.target',)
    conflicts: Sequence[str] = None


@dataclass
class Install(UnitFileSection):
    wanted_by: Sequence[str] = ('multi-user.target',)
    required_by: Sequence[str] = None


@dataclass
class Service(UnitFileSection):
    type: Literal['simple', 'forking', 'oneshot', 'dbus', 'notify', 'idle'] = 'simple'
    remain_after_exit: bool = None
    pid_file: str = None
    bus_name: str = None
    notify_access: Literal['none', 'main', 'all'] = None
    exec_start: str = None
    exec_start_pre: str = None
    exec_start_post: str = None
    exec_reload: str = None
    exec_stop: str = None
    exec_stop_post: str = None
    restart_sec: int = None
    restart: Literal['always', 'on-success', 'on-failure', 'on-abnormal', 'on-abort', 'on-watchdog'] = None
    timeout_sec: int = None
    timeout_start_sec: int = None
    timeout_stop_sec: int = None
    user: str = None


@dataclass
class UnitFile:
    unit: Unit = field(default_factory=Unit)
    install: Install = field(default_factory=Install)
    service: Service = field(default_factory=Service)

    def format(self):
        return '\n\n'.join(getattr(self, f.name).format() for f in fields(self))


# endregion


@dataclass
class RcConfig:
    require: str = 'LOGIN'
    keyword: str = 'shutdown'


def snake_to_pascal_case(text: str) -> str:
    return ''.join(map(str.title, text.split('_')))
