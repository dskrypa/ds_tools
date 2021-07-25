"""
NieR Replicant ver.1.22474487139... Save File reader/editor.

Based on https://github.com/Acurisu/NieR-Replicant-ver.1.22474487139/blob/main/Editor/src/Nier.ts

:author: Doug Skrypa
"""

import json
import logging
from functools import cached_property
from pathlib import Path
from typing import Union, Optional

from tz_aware_dt.utils import format_duration
from ...caching.mixins import DictAttrProperty, ClearableCachedPropertyMixin
from ...output.color import colored
from ...output.formatting import to_hex_and_str
from ...output.printer import PseudoJsonEncoder
from ...utils.diff import unified_byte_diff
from .constants import ABILITIES, CHARACTERS, ONE_HANDED_SWORDS, TWO_HANDED_SWORDS, SPEARS
from .exceptions import UnpackError
from .struct_parts import Savefile as _Savefile
from .structs import FIELD_STRUCT_MAP, GAMEDATA_struct, Savefile_struct, WORD_FLAGS

__all__ = ['Gamedata', 'SaveFile']
log = logging.getLogger(__name__)


class Gamedata:
    def __init__(self, data: bytes):
        self._data = data
        self._unk_1, *self._slots, self._unk_2 = GAMEDATA_struct.unpack(data)
        self.slots = [SaveFile(slot, i) for i, slot in enumerate(self._slots, 1)]

    @classmethod
    def load(cls, path: Union[str, Path]) -> 'Gamedata':
        with Path(path).expanduser().open('rb') as f:
            return cls(f.read())

    @property
    def ok(self):
        return all(f.ok for f in self.slots)

    def __getitem__(self, slot: int):
        return self.slots[slot]


class SaveFile(ClearableCachedPropertyMixin):
    character = DictAttrProperty('processed', 'Character')
    name = DictAttrProperty('processed', 'Name')
    level = DictAttrProperty('processed', 'Level')
    play_time = DictAttrProperty('processed', 'Total Play Time', type=format_duration)

    def __init__(self, data: bytes, slot: int):
        self._slot = slot
        self._data = data

    def __repr__(self):
        name = self.character if self.name.lower() in self.character.lower() else f'{self.name} ({self.character})'
        return f'<SaveFile#{self._slot}[{name}, Lv.{self.level}, play time={self.play_time}]>'

    def __getitem__(self, key: str):
        try:
            return self.processed[key]
        except KeyError:
            return self.data[key]

    @cached_property
    def data(self):
        data = {}
        unpacked = iter(Savefile_struct.unpack(self._data))
        for key, info in _Savefile.items():
            if isinstance(info, list) and len(info) == 3:
                data[key] = [next(unpacked) for _ in range(info[2])]
            else:
                data[key] = next(unpacked)
        return data

    @cached_property
    def checksum(self):
        a, b, c, d = 0, 0, 0, 0
        buf = memoryview(self._data)
        for i in range(0, 0xC20, 8):
            a += buf[i] + buf[i + 4]
            b += buf[i + 1] + buf[i + 5]
            c += buf[i + 2] + buf[i + 6]
            d += buf[i + 3] + buf[i + 7]
        return a + b + c + d

    @property
    def ok(self):
        return self.data['Corruptness'] == 200

    @cached_property
    def processed(self):
        data = {}
        for key, val in self.data.items():
            if key.startswith('unk'):
                continue
            try:
                key_struct, key_fields = FIELD_STRUCT_MAP[key]
            except KeyError:
                data[key] = val
            else:
                try:
                    data[key] = dict(zip(key_fields, key_struct.unpack(val)))
                except Exception as e:
                    raise UnpackError(f'Unable to unpack field={key!r} in save#{self._slot}') from e

        for field in ('Name', 'Map'):
            data[field] = data[field].split(b'\x00', 1)[0].decode('utf-8')
        for field in ('Active Weapon', 'Selected One Handed Sword', 'Selected Spear', 'Selected Two Handed Sword'):
            data[field] = weapon_name(data[field])
        for field in ('Right Bumper', 'Right Trigger', 'Left Bumper', 'Left Trigger'):
            data[field] = ABILITIES[data[field]]

        data['Character'] = CHARACTERS[data['Character']]
        data['Words'] = [w.name for group, group_enum in zip(data['Words'], WORD_FLAGS) for w in group_enum(group)]
        return data

    def diff(self, other: 'SaveFile', max_len: Optional[int] = 30):
        found_difference = False
        for key, own_val in self.data.items():
            other_val = other.data[key]
            if own_val != other_val:
                if not found_difference:
                    found_difference = True
                    print(f'--- {self}')
                    print(f'+++ {other}')

                if max_len and isinstance(own_val, bytes) and len(own_val) > max_len:
                    unified_byte_diff(own_val, other_val, lineterm=key)
                else:
                    print(colored(f'@@ {key} @@', 6))
                    print(colored(f'- {own_val}', 1))
                    print(colored(f'+ {other_val}', 2))

    def view(self, key: str, per_line: int = 40, hide_empty: Union[bool, int] = 10, **kwargs):
        data = self.data[key]
        if isinstance(hide_empty, int):
            hide_empty = (len(data) / per_line) > hide_empty

        offset_fmt = '0x{{:0{}X}}:'.format(len(hex(len(data))) - 2)
        nul = b'\x00' * per_line
        last_os = len(data) // per_line
        is_empty, need_ellipsis = False, True
        for offset in range(0, len(data), per_line):
            nxt = offset + per_line
            line = data[offset:nxt]
            if hide_empty:
                was_empty = is_empty
                if (is_empty := line == nul) and was_empty and offset != last_os and data[nxt: nxt + per_line] == nul:
                    if need_ellipsis:
                        print('...')
                        need_ellipsis = False
                    continue

            need_ellipsis = True
            print(to_hex_and_str(offset_fmt.format(offset), line, fill=per_line, **kwargs))

    def view_unknowns(self, per_line: int = 40, hide_empty: Union[bool, int] = 10, **kwargs):
        for key in self.data:
            if key.startswith('unk'):
                print(colored('\n{}  {}  {}'.format('=' * 30, key, '=' * 30), 14))
                self.view(key, per_line, hide_empty, **kwargs)

    def pprint(self, unknowns: bool = False, **kwargs):
        last_was_view = False
        for key in self.data:
            val = self[key]
            if isinstance(val, bytes):
                if unknowns or not key.startswith('unk'):
                    print(colored('\n{}  {}  {}'.format('=' * 30, key, '=' * 30), 14))
                    self.view(key, **kwargs)
                    last_was_view = True
            else:
                if last_was_view:
                    print()
                if isinstance(val, dict):
                    val = json.dumps(val, sort_keys=True, indent=4, cls=PseudoJsonEncoder)
                print(f'{colored(key, 14)}: {val}')
                last_was_view = False


def weapon_name(index: int):
    if index < 20:
        return ONE_HANDED_SWORDS[index]
    elif index < 40:
        return TWO_HANDED_SWORDS[index - 20]
    return SPEARS[index - 40]
