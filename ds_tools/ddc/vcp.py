"""
API for accessing / controlling a monitor's VCP (Virtual Control Panel).

Originally based on `monitorcontrol <https://github.com/newAM/monitorcontrol>`_
"""

from __future__ import annotations

import logging
import re
from abc import ABC, abstractmethod
from functools import cached_property
from typing import Optional, Union, MutableSet, Collection, Type

from ..core.mixins import Finalizable
from ..core.patterns import FnMatcher
from ..output.color import colored
from .exceptions import VCPError
from .features import Feature, FeatureOrId

__all__ = ['VCP']
log = logging.getLogger(__name__)


class VcpFeature:
    __slots__ = ('code', 'name')

    def __init__(self, code: int):
        self.code = code

    def __set_name__(self, owner: Type[VCP], name: str):
        self.name = name

    def __get__(self, instance: VCP, owner: Type[VCP]):
        return instance.get_feature_value(self.code)

    def __set__(self, instance: VCP, value: int):
        instance.set_feature_value(self.code, value)


class VCP(ABC, Finalizable):
    input = VcpFeature(0x60)

    def __init__(self, n: int):
        self.n = n

    def __repr__(self) -> str:
        return f'<{self.__class__.__name__}[{self.description}]>'

    # region Class Methods

    @classmethod
    def get_monitor(cls, monitor_id: Union[str, int]) -> VCP:
        if isinstance(monitor_id, str) and monitor_id.isdigit():
            monitor_id = int(monitor_id)
        if isinstance(monitor_id, int):
            return cls._get_monitors()[monitor_id]
        return cls.for_id(monitor_id)

    @classmethod
    def get_monitors(cls, *id_patterns: Union[str, int, None]) -> list[VCP]:
        all_monitors = cls._get_monitors()
        id_patterns = {i for i in id_patterns if i is not None}
        str_patterns = {i for i in id_patterns if isinstance(i, str)}
        if not id_patterns or '*' in str_patterns or 'ALL' in str_patterns:
            return sorted(all_monitors)

        nums = {i for i in id_patterns if isinstance(i, int)}
        for i in id_patterns:
            if isinstance(i, str) and i.isdigit():
                str_patterns.remove(i)
                nums.add(int(i))

        monitors = set()
        if str_patterns and isinstance((id_mon_map := getattr(cls, '_monitors', None)), dict):
            for mon_id, monitor in id_mon_map.items():
                log.debug(f'{mon_id=}: {monitor}')

            matches = FnMatcher(str_patterns).match
            monitors.update(monitor for mon_id, monitor in id_mon_map.items() if matches(mon_id))
            if not monitors:
                monitors.update(mon for mon_id, mon in id_mon_map.items() if any(pat in mon_id for pat in id_patterns))
        if nums:
            monitors.update(monitor for i, monitor in enumerate(all_monitors) if i in nums)
        return sorted(monitors)

    @classmethod
    @abstractmethod
    def for_id(cls, monitor_id: str) -> VCP:
        raise NotImplementedError

    @classmethod
    @abstractmethod
    def _get_monitors(cls) -> list[VCP]:
        raise NotImplementedError

    @classmethod
    @abstractmethod
    def _close(cls, *args):
        raise NotImplementedError

    # endregion

    def __getitem__(self, feature: FeatureOrId):
        return self.get_feature_value(feature)

    def __setitem__(self, feature: FeatureOrId, value: int):
        return self.set_feature_value(feature, value)

    def __hash__(self) -> int:
        return hash(self.__class__) ^ hash(self.n)

    def __eq__(self, other: VCP) -> bool:
        return self is other

    def __lt__(self, other: VCP) -> bool:
        return self.n < other.n

    # region Informational Properties

    @property
    @abstractmethod
    def description(self):
        raise NotImplementedError

    @property
    @abstractmethod
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
        raise NotImplementedError

    @cached_property
    def info(self) -> dict[str, str]:
        if not (capabilities := self.capabilities):
            return {}

        info = {}
        for m in re.finditer(r'(([a-z_]+)\(([a-zA-Z0-9.]+|[0-9A-F(). ]+)\)|[A-Z]+)', capabilities):
            brand, token, value = m.groups()
            if not token and not value:
                info['brand'] = brand
            else:
                info[token] = value

        return info

    @cached_property
    def type(self) -> Optional[str]:
        return self.info.get('type')

    @cached_property
    def model(self) -> Optional[str]:
        return self.info.get('model')

    # endregion

    def get_feature(self, feature: FeatureOrId) -> Feature:
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

    def get_feature_value_name(self, feature: FeatureOrId, value: int, default: Optional[str] = None):
        try:
            return self.get_feature(feature).value_names.get(value, default)
        except KeyError:
            return default

    def normalize_feature_value(self, feature: FeatureOrId, value: Union[str, int]) -> int:
        try:
            return int(value, 16)
        except ValueError:
            try:
                return self.get_feature(feature).name_value_map[value]
            except KeyError:
                raise ValueError(f'Unexpected feature {value=!r}')

    @cached_property
    def supported_vcp_values(self) -> dict[Feature, MutableSet[int]]:
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

    def get_supported_values(self, feature: FeatureOrId) -> dict[str, str]:
        feature = self.get_feature(feature)
        if int_values := self.supported_vcp_values.get(feature):
            val_name_map = feature.value_names
            return {f'0x{key:02X}': val_name_map.get(key, '[unknown]') for key in sorted(int_values)}
        else:
            return {}

    @abstractmethod
    def get_feature_value(self, feature: FeatureOrId) -> tuple[int, int]:
        """
        Gets the value of a feature from the virtual control panel.

        :param feature: Feature code
        :return: Tuple of the current value, and its maximum value
        """
        raise NotImplementedError

    @abstractmethod
    def set_feature_value(self, feature: FeatureOrId, value: int):
        """
        Sets the value of a feature on the virtual control panel.

        :param feature: Feature code
        :param value: Feature value
        """
        raise NotImplementedError

    def get_feature_value_with_names(self, feature: FeatureOrId):
        feat_obj = self.get_feature(feature)
        current, max_val = self.get_feature_value(feat_obj.code)
        cur_name = self.get_feature_value_name(feat_obj, current)
        max_name = self.get_feature_value_name(feat_obj, max_val)
        return current, cur_name, max_val, max_name

    def print_capabilities(self, features: Collection[str] = None):
        allow_features = {self.get_feature(f) for f in features} if features else None
        print(f'Monitor {self.n}: {self}')
        log.debug(f'    Raw: {self.capabilities}')
        for feature, values in sorted(self.supported_vcp_values.items()):
            if allow_features and feature not in allow_features:
                continue
            try:
                current, max_val = self[feature]
            except VCPError:
                pass
            else:
                if feature.hide_extras:
                    values = {current}
                elif current not in values:
                    values.add(current)

                print(f'    {feature}:')
                for value in sorted(values):
                    line = f'        0x{value:02X} ({feature.name_for(value, "UNKNOWN")})'
                    print(colored(line, 14) if value == current else line)

    @abstractmethod
    def save_settings(self):
        raise NotImplementedError
