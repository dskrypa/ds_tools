"""
Utilities for parsing and interpreting crontab schedules

:author: Doug Skrypa
"""

from __future__ import annotations

# import logging
from datetime import datetime
from functools import cached_property
from typing import Any, Type, Iterator, Iterable, Mapping, Set

from bitarray import bitarray

__all__ = ['CronSchedule']
# log = logging.getLogger(__name__)

CronDict = dict[int | str, bool]


class TimePart:
    __slots__ = ('cron', 'name', 'arr', 'min', 'special_keys', 'special_vals')

    def __init__(self, cron: CronSchedule, name: str, intervals: int, min: int = 0, special: str = None):  # noqa
        self.cron = cron
        self.name = name
        self.arr = bitarray(intervals)
        self.min = min
        if special:
            self.special_keys = special
            self.special_vals = bitarray(len(special))
        else:
            self.special_keys = None
            self.special_vals = None
        self.reset()

    def reset(self, default: bool = True):
        self.arr.setall(default)
        if self.special_keys:
            self.special_vals.setall(False)

    def _offset(self, key: int) -> int:
        offset_key = key - self.min
        if offset_key < 0:
            raise IndexError(f'Invalid time={key} for part={self.name!r}')
        return offset_key

    def __getitem__(self, key: str | int) -> bool:
        match key:
            case str():
                try:
                    index = self.special_keys.index(key)
                except (ValueError, AttributeError):  # ValueError on key not present; attr error on no special keys
                    return False
                else:
                    return self.special_vals[index]
            case int():
                return self.arr[self._offset(key)]  # noqa
            case _:
                raise TypeError(f'Unexpected type={key.__class__.__name__} for {key=}')  # noqa

    def __setitem__(self, key: str | int, value: bool):
        match key:
            case str():
                try:
                    index = self.special_keys.index(key)
                except (ValueError, AttributeError) as e:  # Value err on key not present; attr err on no special keys
                    raise KeyError(f'Invalid cron schedule {key=} in part={self.name!r}') from e
                else:
                    self.special_vals[index] = value
            case int():
                self.arr[self._offset(key)] = value
            case _:
                raise TypeError(f'Unexpected type={key.__class__.__name__} for {key=}')  # noqa

    def __iter__(self) -> Iterator[int]:
        for i, val in enumerate(self.arr, self.min):
            if val:
                yield i

    def __str__(self) -> str:
        if self.arr.all():
            return '*'

        if not self.arr.any():
            if self['L']:
                return 'L'
            # raise ValueError('Unexpected state')
            return 'X'

        if self.name == 'dow' and not self.cron._week.arr.all():
            week = self.cron._week
            weeks: list[str | int] = list(week)
            if week['L']:
                weeks.append('L')
            return ','.join(f'{v}#{w}' for v in self for w in weeks)
        elif not self['L']:
            size = len(self.arr)
            for divisor in range(2, size // 2 + 1):
                divisible = bitarray(size)
                divisible.setall(False)
                divisible[::divisor] = True
                if divisible == self.arr:
                    return f'*/{divisor}'

        if self['L']:
            return f'{self._collapse_ranges()},L'
        else:
            return self._collapse_ranges()

    def __repr__(self) -> str:
        return f'<{self.__class__.__name__}[{self.name}: {self}]>'

    def all(self) -> bool:
        return all(val for i, val in enumerate(self.arr, self.min))

    def _collapse_ranges(self) -> str:
        ranges = []
        last = None
        for value in self:
            if last is None:
                ranges.append((value, value))
            elif value - last == 1:
                ranges[-1] = (ranges[-1][0], value)
            else:
                ranges.append((value, value))

            last = value

        return ','.join(str(a) if a == b else f'{a}-{b}' for a, b in ranges)

    def set(self, value: str):
        if value == '*':
            self.arr.setall(True)
        elif '/' in value:
            a, divisor = value.split('/', 1)
            if a != '*' or not divisor.isnumeric():
                raise ValueError(f'Invalid cron schedule {value=} in part={self.name!r}')
            self.arr.setall(False)
            self.arr[::int(divisor)] = True
        else:
            parts = set(value.split(','))
            if 'L' in parts:
                self['L'] = True
                parts.remove('L')

            if self.name == 'dow':
                parts = self._normalize_dow_parts(value, parts)

            self._set_intervals_from_parts(value, parts)

    def _normalize_dow_parts(self, value: str, parts: Set[str]) -> Set[str]:  # Using Set due to set method above
        dow_parts = set()
        weeks = set()
        for p in parts:
            if '#' in p:
                val, week = p.split('#')
                dow_parts.add(val)
                if week == 'L':
                    self.cron._week['L'] = True
                else:
                    try:
                        week = int(week)
                    except (TypeError, ValueError):
                        raise ValueError(f'Invalid cron schedule {value=} in {self.name=}')
                    else:
                        if 1 <= week <= 4:
                            weeks.add(week)
                        else:
                            raise ValueError(f'Invalid cron schedule {value=} in {self.name=}')
            else:
                dow_parts.add(p)

        if weeks:
            self.cron._week.set_intervals(weeks)

        return dow_parts

    def _set_intervals_from_parts(self, value: str, parts: Set[str]):
        vals = set()
        for p in parts:
            if '-' in p:
                try:
                    a, b = map(int, p.split('-'))
                except (TypeError, ValueError):
                    raise ValueError(f'Invalid cron schedule {value=} in {self.name=}')
                if a >= b:
                    raise ValueError(f'Invalid cron schedule {value=} in {self.name=}')
                vals.update(range(a, b + 1))
            else:
                try:
                    vals.add(int(p))
                except (TypeError, ValueError):
                    raise ValueError(f'Invalid cron schedule {value=} in {self.name=}')

        self.set_intervals(vals)

    def set_intervals(self, intervals: Mapping[int, bool] | Iterable[int]):
        # log.debug(f'{self!r}: Setting {intervals=}')
        arr = self.arr
        arr.setall(False)
        if isinstance(intervals, Mapping):
            if _min := self.min:
                intervals = {k - _min: v for k, v in intervals.items()}

            # log.debug(f'{self!r}: Setting offset {intervals=}')
            for key, val in intervals.items():
                arr[key] = val
        else:
            if _min := self.min:
                intervals = [v - _min for v in intervals]
            # log.debug(f'{self!r}: Setting offset {intervals=}')
            for key in intervals:
                arr[key] = True

    def replace(self, key: str | int, value: bool):
        self.reset(not value)
        self[key] = value


class CronPart:
    __slots__ = ('intervals', 'min', 'special', 'name')

    def __init__(self, intervals: int, min: int = 0, special: str = None):  # noqa
        self.intervals = intervals
        self.min = min
        self.special = special

    def __set_name__(self, owner: Type[CronSchedule], name: str):
        self.name = name

    def _get(self, instance: CronSchedule) -> TimePart:
        try:
            return instance.__dict__[self.name]
        except KeyError:
            instance.__dict__[self.name] = tp = TimePart(instance, self.name, self.intervals, self.min, self.special)
            return tp

    def __get__(self, instance: CronSchedule | None, owner: Type[CronSchedule]) -> CronPart | TimePart:
        if instance is None:
            return self
        return self._get(instance)

    def __set__(self, instance: CronSchedule, value: Any):
        raise TypeError(f'{self.__class__.__name__} objects do not allow assignment')


class CronSchedule:
    second = CronPart(60)                       # Second
    minute = CronPart(60)                       # Minute
    hour = CronPart(24)                         # Hour
    day = CronPart(31, min=1, special='L')      # Day of month; L = last
    month = CronPart(12, min=1)                 # Month
    dow = CronPart(7)                           # Day of week: 0 = Sunday, 1 = Monday, ... 6 = Saturday, 7 = Sunday
    _week = CronPart(6, min=1, special='L')     # Week of month; L = last (used for DOW & directly by WinCronSchedule)

    def __init__(self, start: datetime = None):
        self._start = start

    def __str__(self) -> str:
        return ' '.join(map(str, (self.second, self.minute, self.hour, self.day, self.month, self.dow)))

    def __repr__(self) -> str:
        return f'<{self.__class__.__name__}[{self}]>'

    def _set_time(self, dt_obj: datetime):
        if dt_obj is not None:
            self.second.replace(dt_obj.second, True)
            self.minute.replace(dt_obj.minute, True)
            self.hour.replace(dt_obj.hour, True)

    @classmethod
    def from_cron(cls, cron_str: str) -> CronSchedule:
        self = cls()
        attrs = (self.second, self.minute, self.hour, self.day, self.month, self.dow)
        for attr, value in zip(attrs, cron_str.split()):
            attr.set(value)
        return self

    @cached_property
    def start(self) -> datetime:
        if self._start:
            return self._start
        dt = datetime.now().replace(
            second=min(self.second), minute=min(self.minute), hour=min(self.hour), microsecond=0
        )
        return dt

    def reset(self):
        for attr in (self.second, self.minute, self.hour, self.day, self.month, self.dow):
            attr.reset()
