"""
API for accessing / controlling a monitor's VCP (Virtual Control Panel).

Originally based on `monitorcontrol <https://github.com/newAM/monitorcontrol>`_
"""

import logging
import re
from abc import ABC, abstractmethod
from functools import cached_property
from typing import List, Optional, Tuple, Union, Dict, MutableSet
from weakref import finalize

from .features import Feature

log = logging.getLogger(__name__)


class VcpFeature:
    def __init__(self, code: int):
        self.code = code

    def __set_name__(self, owner, name):
        self.name = name

    def __get__(self, instance: 'VCP', owner):
        return instance.get_feature_value(self.code)

    def __set__(self, instance: 'VCP', value: int):
        instance.set_feature_value(self.code, value)


class VCP(ABC):
    input = VcpFeature(0x60)

    def __init__(self):
        self.__finalizer = finalize(self, self._close)

    def __repr__(self):
        return f'<{self.__class__.__name__}[{self.description}]>'

    @classmethod
    @abstractmethod
    def get_monitors(cls) -> List['VCP']:
        return NotImplemented

    def close(self):
        try:
            finalizer = self.__finalizer
        except AttributeError:
            pass  # This happens if an exception was raised in __init__
        else:
            if finalizer.detach():
                self._close()

    def __del__(self):
        self.close()

    @abstractmethod
    def _close(self):
        return NotImplemented

    def __enter__(self) -> 'VCP':
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def __getitem__(self, feature: Union[str, int, Feature]):
        return self.get_feature_value(feature)

    def __setitem__(self, feature: Union[str, int, Feature], value: int):
        return self.set_feature_value(feature, value)

    @property
    @abstractmethod
    def description(self):
        return NotImplemented

    @abstractmethod
    @cached_property
    def capabilities(self) -> Optional[str]:
        """
        Example:
            (prot(monitor)type(lcd)SAMSUNGcmds(01 02 03 07 0C E3 F3)vcp(02 04 60( 12 0F 10) FD)mccs_ver(2.1)mswhql(1))

        (
            prot(monitor)
            type(lcd)
            SAMSUNG
            cmds(01 02 03 07 0C E3 F3)
            vcp(02 04 05 08 10 12 14(05 08 0B 0C) 16 18 1A 52 60( 12 0F 10) AA(01 02 03 FF) AC AE B2 B6 C6 C8 C9 D6(01 04 05) DC(00 02 03 05 ) DF FD)
            mccs_ver(2.1)
            mswhql(1)
        )
        """
        return NotImplemented

    @cached_property
    def info(self):
        info = {}
        if self.capabilities:
            for m in re.finditer(r'(([a-z_]+)\(([a-zA-Z0-9.]+|[0-9A-F(). ]+)\)|[A-Z]+)', self.capabilities):
                brand, token, value = m.groups()
                if not token and not value:
                    info['brand'] = brand
                else:
                    info[token] = value

        return info

    @cached_property
    def type(self):
        return self.info.get('type')

    @cached_property
    def model(self):
        return self.info.get('model')

    def get_feature(self, feature: Union[str, int, Feature]) -> Feature:
        if isinstance(feature, Feature):
            return feature
        elif isinstance(feature, int):
            return Feature.for_code(feature, self.description)
        try:
            return Feature.for_name(feature, self.description)
        except KeyError:
            try:
                return Feature.for_code(int(feature, 16), self.description)
            except ValueError:
                raise ValueError(f'Invalid VCP feature: {feature!r}')

    def get_feature_value_name(self, feature: Union[str, int, Feature], value: int, default: Optional[str] = None):
        try:
            return self.get_feature(feature).value_names.get(value, default)
        except KeyError:
            return default

    def normalize_feature_value(self, feature: Union[str, int, Feature], value: Union[str, int]) -> int:
        try:
            return int(value, 16)
        except ValueError:
            try:
                return self.get_feature(feature).name_value_map[value]
            except KeyError:
                raise ValueError(f'Unexpected feature {value=!r}')

    @cached_property
    def supported_vcp_values(self) -> Dict[Feature, MutableSet[int]]:
        supported = {}
        if supported_str := self.info.get('vcp'):
            for m in re.finditer(r'([0-9A-F]{2})(?:\(\s*([^)]+)\)|\s|$|(?=[0-9A-F]))', supported_str):
                code, values = m.groups()
                feature = self.get_feature(code)
                if feature.model or not values:
                    supported[feature] = set(feature.value_names)
                else:
                    supported[feature] = {int(v, 16) for v in values.split()}

        return supported

    def feature_value_map(self, feature: Union[str, int, Feature]):
        try:
            return self.get_feature(feature).value_names
        except (KeyError, ValueError):
            return {}

    def get_supported_values(self, feature: Union[str, int, Feature]) -> Dict[str, str]:
        feature = self.get_feature(feature)
        if int_values := self.supported_vcp_values.get(feature):
            val_name_map = feature.value_names
            return {f'0x{key:02X}': val_name_map.get(key, '[unknown]') for key in sorted(int_values)}
        else:
            return {}

    @abstractmethod
    def set_feature_value(self, feature: Union[str, int, Feature], value: int):
        """
        Sets the value of a feature on the virtual control panel.

        :param feature: Feature code
        :param value: Feature value
        """
        return NotImplemented

    def save_settings(self):
        raise NotImplementedError

    @abstractmethod
    def get_feature_value(self, feature: Union[str, int, Feature]) -> Tuple[int, int]:
        """
        Gets the value of a feature from the virtual control panel.

        :param feature: Feature code
        :return: Tuple of the current value, and its maximum value
        """
        return NotImplemented

    def get_feature_value_with_names(self, feature: Union[str, int, Feature]):
        feat_obj = self.get_feature(feature)
        current, max_val = self.get_feature_value(feat_obj.code)
        cur_name = self.get_feature_value_name(feat_obj, current)
        max_name = self.get_feature_value_name(feat_obj, max_val)
        return current, cur_name, max_val, max_name
