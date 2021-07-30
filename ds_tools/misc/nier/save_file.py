"""
Higher level classes for working with NieR Replicant ver.1.22474487139... save files.

:author: Doug Skrypa
"""

import json
import logging
from datetime import datetime, timedelta
from difflib import unified_diff
from functools import cached_property
from pathlib import Path
from typing import Union, Optional

from construct.lib.containers import ListContainer, Container

from ...core.decorate import cached_classproperty
from ...core.serialization import yaml_dump
from ...caching.mixins import ClearableCachedPropertyMixin
from ...output.color import colored
from ...output.formatting import to_hex_and_str
from ...output.printer import PseudoJsonEncoder
from ...utils.diff import unified_byte_diff
from .constants import MAP_ZONE_MAP, SEED_RESULT_MAP
from .constructs import Gamedata, Savefile, Plot

__all__ = ['GameData', 'SaveFile']
log = logging.getLogger(__name__)


class Constructed:
    def __init_subclass__(cls, construct):  # noqa
        cls._construct = construct

    def __init__(self, data: bytes, parsed=None):
        self._data = data
        self._parsed = parsed or self._construct.parse(data)

    def __getattr__(self, attr: str):
        return _clean(getattr(self._parsed, attr))

    __getitem__ = __getattr__

    @cached_classproperty
    def _offsets_and_sizes(cls):
        offsets_and_sizes = {}
        offset = 0
        for subcon in cls._construct.subcons:
            size = subcon.sizeof()  # TODO: Handle arrays differently?
            offsets_and_sizes[subcon.name] = (offset, size)
            offset += size
        return offsets_and_sizes

    def _build(self):
        return _build(self._parsed)

    def raw(self, key: str) -> bytes:
        offset, size = self._offsets_and_sizes[key]
        return self._data[offset: offset + size]  # noqa

    def raw_items(self):
        for key, (offset, size) in self._offsets_and_sizes.items():
            yield key, self._data[offset: offset + size]

    def diff(self, other: 'Constructed', max_len: Optional[int] = 30, per_line: int = 20, byte_diff: bool = False):
        found_difference = False
        for key, own_raw in self.raw_items():
            own_val = self[key]
            other_raw = other.raw(key)
            if own_raw != other_raw:
                if not found_difference:
                    found_difference = True
                    print(f'--- {self}')
                    print(f'+++ {other}')

                if isinstance(self, GameData) and key == 'slots':
                    for own_slot, other_slot in zip(self.slots, other.slots):
                        own_slot.diff(other_slot, max_len, per_line, byte_diff)
                elif not byte_diff and own_val != own_raw and not isinstance(own_val, (float, int, str)):
                    print(colored(f'@@ {key} @@', 6))
                    a, b = yaml_dump(own_val).splitlines(), yaml_dump(other[key]).splitlines()
                    for i, line in enumerate(unified_diff(a, b, n=2, lineterm='')):
                        if line.startswith('+'):
                            if i > 1:
                                print(colored(line, 2))
                        elif line.startswith('-'):
                            if i > 1:
                                print(colored(line, 1))
                        elif not line.startswith('@@ '):
                            print(line)
                elif max_len and isinstance(own_raw, bytes) and len(own_raw) > max_len:
                    unified_byte_diff(own_raw, other_raw, lineterm=key, struct=repr, per_line=per_line)
                else:
                    print(colored(f'@@ {key} @@', 6))
                    print(colored(f'- {own_val}', 1))
                    print(colored(f'+ {other[key]}', 2))

    def view(self, key: str, per_line: int = 40, hide_empty: Union[bool, int] = 10, **kwargs):
        data = self.raw(key)
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
        for key in self._offsets_and_sizes:
            if key.startswith('_unk'):
                print(colored('\n{}  {}  {}'.format('=' * 30, key, '=' * 30), 14))
                self.view(key, per_line, hide_empty, **kwargs)

    def pprint(self, unknowns: bool = False, **kwargs):
        last_was_view = False
        for key in self._offsets_and_sizes:
            val = self[key]
            if isinstance(val, bytes):
                if unknowns or not key.startswith('_unk'):
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


class GameData(Constructed, construct=Gamedata):
    def __init__(self, data: bytes):
        super().__init__(data)
        self._parsed: Gamedata = self._construct.parse(data)
        self.slots = [SaveFile(slot, i) for i, slot in enumerate(self._parsed.slots, 1)]

    @classmethod
    def load(cls, path: Union[str, Path]) -> 'Gamedata':
        with Path(path).expanduser().open('rb') as f:
            return cls(f.read())

    def save(self, path: Union[str, Path]):
        with Path(path).expanduser().open('wb') as f:
            f.write(self._construct.build(self._build()))

    @property
    def ok(self) -> bool:
        return all(f.ok for f in self.slots)

    def __getitem__(self, slot_or_key: Union[int, str]):
        try:
            return self.slots[slot_or_key] if isinstance(slot_or_key, int) else getattr(self._parsed, slot_or_key)
        except AttributeError as e:
            raise KeyError(slot_or_key) from e

    def __iter__(self):
        yield from self.slots


class SaveFile(ClearableCachedPropertyMixin, Constructed, construct=Savefile):
    def __init__(self, slot, num: int):
        super().__init__(slot.data, slot.value)
        self._num = num

    def __repr__(self):
        name = self.character if self.name.lower() in self.character.lower() else f'{self.name} ({self.character})'
        return (
            f'<SaveFile#{self._num}[{name}, Lv.{self.level} @ {self.location}][{self.play_time}]'
            f'[{self.save_time.isoformat(" ")}]>'
        )

    @property
    def ok(self):
        return self._parsed.corruptness == 200

    @cached_property
    def play_time(self):
        hours, seconds = divmod(int(self._parsed.total_play_time), 3600)
        minutes, seconds = divmod(seconds, 60)
        return f'{hours:01d}:{minutes:02d}:{seconds:02d}'

    @cached_property
    def known_words(self):
        return [w for w, v in self.words.items() if v]

    @cached_property
    def location(self):
        loc_part = '_'.join(self._parsed.map.split('_')[1:3])
        return MAP_ZONE_MAP.get(loc_part, self._parsed.map)

    @cached_property
    def garden(self):
        return [[GardenPlot(plot, r, i) for i, plot in enumerate(row)] for r, row in enumerate(self._parsed.garden)]

    def show_garden(self, func=str):
        columns = [list(map(func, row)) for row in self.garden]
        row_fmt = '{{:>{}s}}  {{:>{}s}}  {{:>{}s}}'.format(*(max(map(len, col)) for col in columns))
        print('\n'.join(row_fmt.format(*row) for row in zip(*columns)))

    def iter_garden_plots(self):
        for row in self.garden:
            yield from row

    def set_plant_times(self, dt: datetime = None, hours: int = None):
        if (dt and hours) or (not dt and not hours):
            raise ValueError(f'set_plant_times() requires ONE of dt or hours')
        dt = dt or (datetime.now() - timedelta(hours=hours))
        for plot in self.iter_garden_plots():
            if plot._parsed.seed != 255:
                plot._parsed.time = dt


class GardenPlot(ClearableCachedPropertyMixin, Constructed, construct=Plot):
    def __init__(self, plot, row: int, num: int):
        super().__init__(plot.data, plot.value)
        self._row = row
        self._num = num

    @cached_property
    def watered(self):
        return ''.join('\u25cb' if v else '\u2715' for k, v in self.water.items() if k != '_flagsenum')

    def __str__(self):
        planted = self.time.isoformat(' ') if self.time else None
        plant = SEED_RESULT_MAP.get(self.seed, self.seed)
        plant = 'None' if plant == 255 else plant
        fertilizer = self.fertilizer.split()[0]
        unk = self.raw('_unk2')[-4:].hex()
        return f'\u2039{plant} | F:{fertilizer} | W:{self.watered} | {planted} | {unk}\u203a'

    def __repr__(self):
        planted = self.time.isoformat(' ') if self.time else None
        return (
            f'<GardenPlot[{self._row}x{self._num} @ {planted}, {self.seed} + {self.fertilizer} (watered:'
            f' {self.watered})]({self._data[:-8].hex(" ", -4)})>'
        )

    __serializable__ = __repr__


def _build(obj):
    if isinstance(obj, ListContainer):
        return [_build(li) for li in obj]
    elif isinstance(obj, Container):
        if set(obj) == {'offset1', 'length', 'offset2', 'data', 'value'}:
            return {'value': _build(obj.value)}
        return {key: _build(val) for key, val in obj.items() if key != '_io'}
    else:
        return obj


def _clean(obj):
    if isinstance(obj, ListContainer):
        return [_clean(li) for li in obj]
    elif isinstance(obj, Container):
        if set(obj) == {'offset1', 'length', 'offset2', 'data', 'value'}:
            return _clean(obj.value)
        return {key: _build(val) for key, val in obj.items() if key not in ('_io', '_flagsenum')}
    else:
        return obj
