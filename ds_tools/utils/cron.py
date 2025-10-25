"""
Utilities for parsing and interpreting crontab schedules

:author: Doug Skrypa
"""

from __future__ import annotations

# import logging
from datetime import datetime
from functools import cached_property
from typing import Any, Iterator, Iterable, Literal, Mapping, Set, Type, TypeVar

from bitarray import bitarray

__all__ = ['CronSchedule', 'ExtCronSchedule', 'CronError', 'InvalidCronSchedule']
# log = logging.getLogger(__name__)

CronDict = dict[int | str, bool]
PartIndex = TypeVar('PartIndex', int, slice)
L = Literal['L']
PartKey = PartIndex | L


# region Time Parts


class TimePart:
    __slots__ = ('cron', 'name', 'arr', 'min', 'special_keys', 'special_vals')

    def __init__(self, cron: CronSchedule, name: str, intervals: int, min: int = 0, special: str = None):  # noqa
        self.cron = cron
        self.name = name
        self.arr = bitarray(intervals)  # initializes all values to False
        self.min = min
        if special:
            self.special_keys = special
            self.special_vals = bitarray(len(special))
        else:
            self.special_keys = None
            self.special_vals = None

    def set(self, value: str):
        if value == '*':
            self.arr.setall(True)
            return

        self.arr.setall(False)
        for part in _parse_slices(value, self.min, len(self.arr)):
            self[part] = True

    def reset(self, default: bool = True):
        self.arr.setall(default)
        if self.special_keys:
            self.special_vals.setall(False)

    def all(self) -> bool:
        return all(val for i, val in enumerate(self.arr, self.min))

    # region Get / Set Specific Times

    def __getitem__(self, key: PartKey) -> bool:
        match key:
            case int() | slice():
                return self.arr[self._offset(key)]  # noqa
            case str():
                try:
                    index = self.special_keys.index(key)
                except (ValueError, AttributeError):  # ValueError on key not present; attr error on no special keys
                    return False
                else:
                    return self.special_vals[index]
            case _:
                raise TypeError(f'Unexpected type={key.__class__.__name__} for {key=}')  # noqa

    def __setitem__(self, key: PartKey, value: bool):
        match key:
            case int() | slice():
                self.arr[self._offset(key)] = value
            case str():
                try:
                    index = self.special_keys.index(key)
                except (ValueError, AttributeError) as e:  # Value err on key not present; attr err on no special keys
                    raise KeyError(f'Invalid cron schedule {key=} in part={self.name!r}') from e
                else:
                    self.special_vals[index] = value
            case _:
                raise TypeError(f'Unexpected type={key.__class__.__name__} for {key=}')  # noqa

    def _offset(self, key: PartIndex) -> PartIndex:
        match key:
            case int():
                offset_key = key - self.min
                if offset_key < 0:
                    raise IndexError(f'Invalid time={key} for part={self.name!r}')
                return offset_key
            case slice():
                if self.min:
                    return slice(
                        (key.start - self.min) if key.start is not None else None,
                        (key.stop - self.min) if key.stop is not None else None,
                        key.step,
                    )
                else:
                    return key
            case _:
                raise TypeError(f'Unexpected type={key.__class__.__name__} for {key=}')

    def __iter__(self) -> Iterator[int]:
        """Yields times when this part is enabled."""
        if offset := self.min:
            for index in self.arr.search(1):
                yield index + offset
        else:
            yield from self.arr.search(1)  # Yields indexes where the value is True (1)

    def _iter_all(self) -> Iterator[int | L]:
        """Yields times (and special keys, if present) when this part is enabled."""
        yield from self
        if self['L']:
            yield 'L'  # noqa

    # endregion

    # region str / repr

    def __repr__(self) -> str:
        return f'<{self.__class__.__name__}[{self.name}: {self}]>'

    def __str__(self) -> str:
        if self.arr.all():
            return '*'
        elif step_str := self._get_step_str():
            return step_str
        else:
            return self._collapse_ranges()

    def _get_step_str(self) -> str | None:
        if not self.arr.any():
            return None

        size = len(self.arr)
        divisible = bitarray(size)
        for step in range(2, size // 2 + 1):
            divisible.setall(False)
            divisible[::step] = True
            if divisible == self.arr:
                return f'*/{step}'

        return None

    def _collapse_ranges(self) -> str:
        return ','.join(str(a) if a == b else f'{a}-{b}' for a, b in self._iter_ranges())

    def _iter_ranges(self) -> Iterator[tuple[int, int] | tuple[L, L]]:
        start = last = None
        for value in self:
            if start is None:
                start = last = value
            elif value - last == 1:
                last = value
            else:
                yield start, last
                start = last = value

        if start is not None:
            yield start, last

        if self['L']:  # Only possible for day (of month) and week, but this will never be called for week
            yield 'L', 'L'  # noqa

    # endregion

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


class DayOfWeekPart(TimePart):
    __slots__ = ()

    def __str__(self) -> str:
        if self.arr.all():
            return '*'
        elif not self.arr.any():
            # raise ValueError('Unexpected state')
            return 'X'
        elif not self.cron._week.arr.all():
            return ','.join(f'{v}#{w}' for v in self for w in self.cron._week._iter_all())
        elif step_str := self._get_step_str():
            return step_str
        else:
            return self._collapse_ranges()

    def set(self, value: str):
        if value == '*':
            self.arr.setall(True)
            return

        if '/' in value:
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


# endregion


class CronPart:
    """
    Descriptor that enables unique :class:`TimePart` objects to be initialized for each parent :class:`CronSchedule`.
    """
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
            part_cls = DayOfWeekPart if self.name == 'dow' else TimePart
            instance.__dict__[self.name] = tp = part_cls(instance, self.name, self.intervals, self.min, self.special)
            return tp

    def __get__(self, instance: CronSchedule | None, owner: Type[CronSchedule]) -> CronPart | TimePart:
        if instance is None:
            return self
        return self._get(instance)

    def __set__(self, instance: CronSchedule, value: Any):
        raise TypeError(f'{self.__class__.__name__} objects do not allow assignment')


class CronSchedule:
    minute = CronPart(60)                       # Minute
    hour = CronPart(24)                         # Hour
    day = CronPart(31, min=1, special='L')      # Day of month; L = last
    month = CronPart(12, min=1)                 # Month
    dow = CronPart(7)  # Day of week: 0 = Sunday, 1 = Monday, ... 6 = Saturday, 7 = Sunday; L = last (stored in _week)
    _week = CronPart(6, min=1, special='L')     # Week of month; L = last (used for DOW & directly by WinCronSchedule)

    def __init__(self, cron_str: str):
        self._week.reset()  # Must be set to all True before processing DOW
        try:
            for part, value in zip(self._parts(), cron_str.split(), strict=True):
                part.set(value)
        except ValueError as e:
            raise InvalidCronSchedule(cron_str) from e

    def _parts(self) -> tuple[TimePart, ...]:
        return self.minute, self.hour, self.day, self.month, self.dow  # noqa

    def __str__(self) -> str:
        return ' '.join(map(str, self._parts()))

    def __repr__(self) -> str:
        return f'<{self.__class__.__name__}[{self}]>'

    def reset(self):
        for part in self._parts():
            part.reset()


class ExtCronSchedule(CronSchedule):
    second = CronPart(60)

    def _parts(self) -> tuple[TimePart, ...]:
        return self.second, self.minute, self.hour, self.day, self.month, self.dow  # noqa


def _parse_slices(cron_expr: str, min_val: int, max_val: int) -> Iterator[slice | int | Literal['L']]:
    for part in cron_expr.split(','):
        if part == 'L':
            yield part
        else:
            yield _parse_slice(part, min_val, max_val)


def _parse_slice(expr_part: str, min_val: int, max_val: int) -> slice | int:
    try:
        value = int(expr_part)
    except ValueError:
        pass
    else:
        if min_val <= value < max_val:
            return value
        raise ValueError(f'Invalid {value=} - expected {min_val} <= value < {max_val}')

    try:
        range_expr, step = expr_part.split('/', 1)
    except ValueError:
        pass
    else:
        try:
            step = int(step)
        except ValueError as e:
            raise ValueError(f'Invalid {step=} value - expected a positive int') from e
        if step >= 1:
            return slice(*_parse_range_expr(range_expr, min_val, max_val), step)
        raise ValueError(f'Invalid {step=} value - expected a positive int')

    return slice(*_parse_range_expr(expr_part, min_val, max_val))


def _parse_range_expr(range_expr: str, min_val: int, max_val: int) -> tuple[int | None, int | None]:
    if range_expr == '*':
        return None, None

    try:
        value = int(range_expr)
    except ValueError:
        pass
    else:
        if min_val <= value < max_val:
            return value, None
        raise ValueError(f'Invalid {value=} - expected {min_val} <= value < {max_val}')

    try:
        start, stop = map(int, range_expr.split('-', 1))
    except ValueError:
        pass
    else:
        if min_val <= start <= stop:
            return start, (None if stop >= max_val else stop + 1)
        raise ValueError(f'Invalid range - expected {min_val} <= {start=} <= {stop=}')

    raise ValueError(f"Invalid {range_expr=} - expected '*', an int, or int-int")


class CronError(Exception):
    pass


class InvalidCronSchedule(CronError, ValueError):
    """Raised when an invalid cron schedule is provided."""
