"""
Originally based on `monitorcontrol.vcp.vcp_linux <https://github.com/newAM/monitorcontrol>`_
"""

from __future__ import annotations

import logging
from functools import cached_property
from pathlib import Path
from typing import TYPE_CHECKING
from weakref import finalize

from ..exceptions import VCPIOError
from ..vcp import VCP
from .constants import DDCPacketType
from .i2c import I2CFile, I2CIoctlClient, DDCCIClient, Capabilities

if TYPE_CHECKING:
    from ..features import FeatureOrId

__all__ = ['LinuxVCP']
log = logging.getLogger(__name__)


class LinuxVCP(VCP):
    _monitors = []

    def __init__(self, n: int, path: Path, ignore_checksum_errors: bool = True):
        super().__init__(n)
        self.path = path  # /dev/i2c-*
        # self.last_write = 0
        self.ignore_checksum_errors = ignore_checksum_errors

    # region Initializers / Class Methods

    @classmethod
    def for_id(cls, monitor_id: str) -> LinuxVCP:
        raise NotImplementedError

    @classmethod
    def _get_monitors(cls, ignore_checksum_errors: bool = True) -> list[LinuxVCP]:
        if not cls._monitors:
            for num, path in sorted((int(path.name.rsplit('-', 1)[1]), path) for path in Path('/dev').glob('i2c-*')):
                vcp = cls(num, path, ignore_checksum_errors)
                try:
                    vcp._file  # noqa
                except (OSError, VCPIOError):
                    pass
                else:
                    cls._monitors.append(vcp)
        return cls._monitors

    # endregion

    # region I2C IO

    @cached_property
    def _file(self) -> I2CFile:
        file = I2CFile(self.path)
        self._finalizer = finalize(self, self._close, file)
        return file

    @cached_property
    def _ioctl(self) -> I2CIoctlClient:
        return I2CIoctlClient(self._file)

    @cached_property
    def _ddcci(self) -> DDCCIClient:
        return DDCCIClient(self._ioctl)

    @classmethod
    def _close(cls, file: I2CFile):
        file.close()

    # endregion

    @cached_property
    def capabilities(self) -> str | None:
        return self._ddcci.get_str(Capabilities)

    @property
    def description(self) -> str:
        # TODO: `ddcutil detect`
        return self.path.as_posix()

    def set_feature_value(self, feature: FeatureOrId, value: int):
        feature = self.get_feature(feature)
        return self._ddcci.request(DDCPacketType.SET_VCP_REQUEST, feature.code, value)

    def get_feature_value(self, feature: FeatureOrId) -> tuple[int, int]:
        feature = self.get_feature(feature)
        return self._ddcci.request(DDCPacketType.QUERY_VCP_REQUEST, feature.code)

    def save_settings(self):
        pass
