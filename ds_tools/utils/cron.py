"""
Utilities for parsing and interpreting crontab schedules

:author: Doug Skrypa
"""

from __future__ import annotations

from typing import Any, Iterator, Iterable, Literal, Type, TypeVar

from bitarray import bitarray

__all__ = ['CronSchedule', 'ExtCronSchedule', 'CronError', 'InvalidCronSchedule', 'InvalidCronPart']

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

    def set(self, part_expr: str):
        if part_expr == '*':
            self.arr.setall(True)
            return

        self.arr.setall(False)
        try:
            for part in self._parse_slices(part_expr):
                self[part] = True
        except ValueError as e:
            raise InvalidCronPart(self.name, part_expr, str(e)) from e

    def _parse_slices(self, part_expr: str) -> Iterator[slice | int | L]:
        max_val = len(self.arr)
        for part in part_expr.split(','):
            if part == 'L':
                yield part
            else:
                yield _parse_slice(part, self.min, max_val)

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

    def set_all(self, keys: Iterable[PartKey], value: bool, exclusive: bool = True):
        """
        :param keys: Keys for which the given value should be set
        :param value: The value to store for the given keys
        :param exclusive: If True (the default), set all array values to the inverse of the provided value before
          storing the provided value.
        """
        if exclusive:
            self.arr.setall(not value)

        for key in keys:
            self[key] = value

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
            return ','.join(self._iter_ranges())

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

    def _iter_ranges(self) -> Iterator[str]:
        start = last = None
        for value in self:
            if start is None:
                start = last = value
            elif value - last == 1:
                last = value
            else:
                yield str(start) if start == last else f'{start}-{last}'
                start = last = value

        if start is not None:
            yield str(start) if start == last else f'{start}-{last}'

        if self['L']:  # Only possible for day (of month) and week, but this will never be called for week
            yield 'L'

    # endregion

    def replace(self, key: str | int, value: bool):
        self.reset(not value)
        self[key] = value


class DayOfWeekPart(TimePart):
    """
    TimePart representing days of the week.

    Values may be specified like any other time part, or as ``dow#week`` where ``week`` is an integer or ``'L'`` to
    represent the last week of the month.
    """
    __slots__ = ('week_days_map',)
    week_days_map: dict[int | L, bitarray]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.week_days_map = {}

    def __str__(self) -> str:
        if self.arr.all():
            return '*'
        elif step_str := self._get_step_str():
            return step_str
        else:
            return ','.join(self._iter_ranges())

    def _get_step_str(self) -> str | None:
        if self.week_days_map:
            return None
        return super()._get_step_str()

    def _iter_ranges(self) -> Iterator[str]:
        yield from super()._iter_ranges()
        yield from sorted(f'{day}#{week}' for week, arr in self.week_days_map.items() for day in arr.search(1))

    def _parse_slices(self, cron_expr: str) -> Iterator[slice | int | L]:
        max_val = len(self.arr)
        for part in cron_expr.split(','):
            if part == 'L':
                yield part
            elif '#' in part:
                self._handle_dow_in_week(part)
            else:
                yield _parse_slice(part, self.min, max_val)

    def _handle_dow_in_week(self, part: str):
        range_expr, week = part.split('#', 1)
        self.set_day_in_week(_parse_week(week), _parse_slice(range_expr, 0, 8))

    def set_day_in_week(self, week: int | L, day: int | slice):
        arr = self._get_week_array(week)
        match day:
            case int():
                arr[day % 7] = True
            case slice():
                for d in range(day.start, day.stop, day.step):
                    arr[d % 7] = True

    def _get_week_array(self, week: int | L) -> bitarray:
        try:
            return self.week_days_map[week]
        except KeyError:
            self.week_days_map[week] = arr = bitarray(7)
            return arr


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


# region Cron Schedule


class CronSchedule:
    minute = CronPart(60)                       # Minute
    hour = CronPart(24)                         # Hour
    day = CronPart(31, min=1, special='L')      # Day of month; L = last
    month = CronPart(12, min=1)                 # Month
    dow = CronPart(7)                           # Day of week: 0 = Sunday, 1 = Monday, ... 6 = Saturday, 7 = Sunday

    def __init__(self, cron_str: str):
        try:
            for part, value in zip(self._parts(), cron_str.split(), strict=True):
                part.set(value)
        except CronError:
            raise  # propagate errors from this module (some of them extend ValueError)
        except ValueError as e:
            # expected to be raised by zip with too few/many parts
            raise InvalidCronSchedule(cron_str, f'expected {len(self._parts())} parts separated by spaces') from e

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


# endregion


# region Parsing Helpers


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


def _parse_week(week: str) -> int | L:
    if week == 'L':
        return week

    try:
        week = int(week)
    except ValueError as e:
        raise ValueError(f"Invalid {week=} - expected an int between 1 and 4 (inclusive) or 'L'") from e

    if 1 <= week <= 4:
        return week
    else:
        raise ValueError(f"Invalid {week=} - expected an int between 1 and 4 (inclusive) or 'L'")


# endregion


# region Exceptions


class CronError(Exception):
    pass


class InvalidCronPart(CronError, ValueError):
    def __init__(self, part_name: str, part_expr: str, message: str):
        self.part_name = part_name
        self.part_expr = part_expr
        self.message = message

    def __str__(self) -> str:
        return f'Invalid {self.part_name}={self.part_expr!r} - {self.message}'


class InvalidCronSchedule(CronError, ValueError):
    """Raised when an invalid cron schedule is provided."""

    def __init__(self, cron_expr: str, message: str):
        self.cron_expr = cron_expr
        self.message = message

    def __str__(self) -> str:
        return f'Invalid cron_expr={self.cron_expr!r} - {self.message}'


# endregion
