from __future__ import annotations

import logging
from winreg import HKEY_LOCAL_MACHINE

from .base import Node, NodeAttribute
from .enums import DeviceState

__all__ = ['AudioDevice']
log = logging.getLogger(__name__)

OUTPUT_DEVICES_DIR = r'SOFTWARE\Microsoft\Windows\CurrentVersion\MMDevices\Audio\Render'


class AudioDevice(Node):
    device_state: DeviceState = NodeAttribute('DeviceState', type=DeviceState)
    device_name: str = NodeAttribute('{a45c254e-df1c-4efd-8020-67d146a850e0},2', 'Properties')
    device_class: str = NodeAttribute('{a45c254e-df1c-4efd-8020-67d146a850e0},24', 'Properties')
    controller_name: str = NodeAttribute('{b3f8fa53-0004-438e-9003-51a46e139bfc},6', 'Properties')

    def __init__(self, guid: str):
        super().__init__(HKEY_LOCAL_MACHINE, f'{OUTPUT_DEVICES_DIR}\\{guid}')

    @classmethod
    def find_all(cls) -> list[AudioDevice]:
        return [cls(guid) for guid in Node(HKEY_LOCAL_MACHINE, OUTPUT_DEVICES_DIR)._key_names]

    def as_dict(self, recursive: bool = True, children: bool = True):
        data = super().as_dict(recursive, children)
        data['audio_device_info'] = {
            'device_state': self.device_state.name,
            'device_name': self.device_name,
            'device_class': self.device_class,
            'controller_name': self.controller_name,
        }
        return data
