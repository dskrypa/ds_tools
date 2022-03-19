import platform as _platform

_system = _platform.system().lower()
if _system == 'freebsd':
    from .rc import RcService as Service
elif _system == 'linux':
    from .systemd import SystemdService as Service
else:
    from .base import Service

del _system
del _platform
