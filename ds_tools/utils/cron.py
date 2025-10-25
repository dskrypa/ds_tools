"""
Utilities for parsing and interpreting crontab schedules

:author: Doug Skrypa
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, time
from itertools import pairwise
from typing import Any, Iterator, Iterable, Literal, Type, TypeVar, overload

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
        return self.arr.all()

    # region Get / Set Specific Times

    @overload
    def __getitem__(self, key: int | str) -> bool:
        ...

    @overload
    def __getitem__(self, key: slice) -> bitarray:
        ...

    def __getitem__(self, key):
        match key:
            case int() | slice():
                return self.arr[self._offset(key)]
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

    def replace(self, key: str | int, value: bool):
        self.reset(not value)
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

    def _iter(self, right: bool = False):
        """Yields times when this part is enabled."""
        if offset := self.min:
            for index in self.arr.search(1, right=right):
                yield index + offset
        else:
            yield from self.arr.search(1, right=right)  # Yields indexes where the value is True (1)

    def __iter__(self) -> Iterator[int]:
        """Yields times when this part is enabled."""
        return self._iter()

    def __reversed__(self) -> Iterator[int]:
        return self._iter(True)

    def _iter_all(self) -> Iterator[int | L]:
        """Yields times (and special keys, if present) when this part is enabled."""
        yield from self
        if self['L']:
            yield 'L'  # noqa

    def _get_last(self) -> int | None:
        if self['L']:
            return len(self.arr) + self.min - 1

        last = self.arr.find(1, right=True)
        return None if last == -1 else last

    # endregion

    # region str / repr

    def __repr__(self) -> str:
        return f'<{self.__class__.__name__}[{self.name}: {self}]>'

    def __str__(self) -> str:
        if self.arr.all():
            return '*'
        elif step := self._get_step_val():
            return f'*/{step}'
        else:
            return ','.join(self._iter_ranges())

    def _get_step_val(self) -> int | None:
        if not self.arr.any():
            return None

        size = len(self.arr)
        divisible = bitarray(size)
        for step in range(2, size // 2 + 1):
            divisible.setall(False)
            divisible[::step] = True
            if divisible == self.arr:
                return step

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

    def matches(self, dt: datetime | date) -> bool:
        if self.all() or self[getattr(dt, self.name)]:
            return True
        # Note: L is only possible for day
        return self['L'] and (dt + timedelta(days=1)).month != dt.month


class MonthPart(TimePart):
    __slots__ = ()

    def matches(self, dt: datetime | date) -> bool:
        return self.all() or self[dt.month]

    def matching_dates(self, year: int, month: int, reverse: bool = False) -> Iterator[date]:
        if self.all() or self[month]:
            day, dow = self.cron.day, self.cron.dow
            if day.all() and dow.all():
                yield from _dates(year, month, reverse=reverse)
            else:
                for dt in _dates(year, month, reverse=reverse):
                    if day.matches(dt) and dow.matches(dt):
                        yield dt


class DayOfWeekPart(TimePart):
    """
    TimePart representing days of the week.

    0 = Sunday, 1 = Monday, ... 6 = Saturday, 7 = Sunday

    Values may be specified like any other time part, or as ``dow#week`` where ``week`` is an integer or ``'L'`` to
    represent the last week of the month.
    """
    __slots__ = ('week_days_map',)
    week_days_map: dict[int | L, bitarray]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.week_days_map = {}

    def matches(self, dt: datetime | date) -> bool:
        if self.all():
            return True

        dow = dt.isoweekday() % 7
        if self[dow]:
            return True

        if self.week_days_map:
            first_week = dt.replace(day=1).isocalendar().week
            dt_week = dt.isocalendar().week
            try:
                if self.week_days_map[dt_week - first_week + 1][dow]:
                    return True
            except KeyError:
                pass

            if self.week_days_map['L'] and _last_day_of_month(dt).isocalendar().week == dt_week:
                return True

        return False

    def __str__(self) -> str:
        if self.arr.all():
            return '*'
        elif step := self._get_step_val():
            return f'*/{step}'
        else:
            return ','.join(self._iter_ranges())

    def _get_step_val(self) -> int | None:
        if self.week_days_map:
            return None
        return super()._get_step_val()

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


_PART_NAME_CLS_MAP = {'dow': DayOfWeekPart, 'month': MonthPart}
TP = TypeVar('TP', bound=TimePart)


class CronPart[TP]:
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

    def _get(self, instance: CronSchedule) -> TP:
        try:
            return instance.__dict__[self.name]
        except KeyError:
            part_cls = _PART_NAME_CLS_MAP.get(self.name, TimePart)
            instance.__dict__[self.name] = tp = part_cls(instance, self.name, self.intervals, self.min, self.special)
            return tp

    def __get__(self, instance: CronSchedule | None, owner: Type[CronSchedule]) -> CronPart | TP:
        if instance is None:
            return self
        return self._get(instance)

    def __set__(self, instance: CronSchedule, value: Any):
        raise TypeError(f'{self.__class__.__name__} objects do not allow assignment')


# region Cron Schedule


class CronSchedule:
    minute = CronPart[TimePart](60)                     # Minute
    hour = CronPart[TimePart](24)                       # Hour
    day = CronPart[TimePart](31, min=1, special='L')    # Day of month; L = last
    month = CronPart[MonthPart](12, min=1)              # Month
    dow = CronPart[DayOfWeekPart](7)                    # Day of week: 0=Sunday, 1=Monday, ... 6=Saturday, 7=Sunday

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

    # region Match Methods

    def matches(self, dt: datetime) -> bool:
        return all(part.matches(dt) for part in self._parts())

    def first_match_of_year(self, year: int) -> datetime:
        return datetime.combine(next(self._matching_days(year)), next(self._matching_times()))

    def last_match_of_year(self, year: int) -> datetime:
        return datetime.combine(next(self._matching_days(year, reverse=True)), next(self._matching_times(reverse=True)))

    def matches_after(self, now: datetime | date | None = None) -> Iterator[datetime]:
        yield from CronMatchIterator(self, now)

    def matching_datetimes(self, year: int | None = None, reverse: bool = False) -> Iterator[datetime]:
        if year is None:
            year = date.today().year

        times = list(self._matching_times(reverse=reverse))
        combine = datetime.combine
        for day in self._matching_days(year, reverse=reverse):
            for t in times:
                yield combine(day, t)

    def _matching_days(self, year: int, *, start_month: int = None, reverse: bool = False) -> Iterator[date]:
        months = self.month._iter(reverse)
        if start_month is not None:
            months = (m for m in months if m <= start_month) if reverse else (m for m in months if m >= start_month)

        day, dow = self.day, self.dow
        for month in months:
            if day.all() and dow.all():
                yield from _dates(year, month, reverse=reverse)
            else:
                for dt in _dates(year, month, reverse=reverse):
                    if day.matches(dt) and dow.matches(dt):
                        yield dt

    def _matching_times(self, reverse: bool = False) -> Iterator[time]:
        minute = self.minute
        minute_range = range(59, -1, -1) if reverse else range(60)
        for hour in self.hour._iter(reverse):
            if minute.all():
                for m in minute_range:
                    yield time(hour, m)
            else:
                for m in minute_range:
                    if minute[m]:
                        yield time(hour, m)

    # endregion

    def get_intervals(self, year: int | None = None) -> set[float]:
        if self.day.all() and self.month.all() and self.dow.all():
            if self.hour.all() and (step := self.minute._get_step_val()):
                return {step}
            return {(b - a).total_seconds() for a, b in pairwise(self._get_intervals_times())}

        if not year:
            year = date.today().year

        intervals = {(b - a).total_seconds() for a, b in pairwise(self.matching_datetimes(year))}
        intervals.add((self.first_match_of_year(year) - self.last_match_of_year(year - 1)).total_seconds())
        return intervals

    def _get_intervals_times(self) -> Iterator[datetime]:
        combine = datetime.combine
        today = date.today()
        times = list(self._matching_times())
        yield combine(today - timedelta(days=1), times[-1])
        for t in times:
            yield combine(today, t)


class ExtCronSchedule(CronSchedule):
    second = CronPart(60)

    def _parts(self) -> tuple[TimePart, ...]:
        return self.second, self.minute, self.hour, self.day, self.month, self.dow  # noqa


class CronMatchIterator:
    __slots__ = ('cron', 'times', 'now')

    def __init__(self, cron: CronSchedule, now: datetime | date | None = None):
        self.cron = cron
        self.times = list(cron._matching_times())
        if not now:
            self.now = datetime.now()
        elif isinstance(now, date):
            self.now = datetime.combine(now, datetime.now().time())
        else:
            self.now = now

    def __iter__(self) -> Iterator[datetime]:
        yield from self._iter_this_year()

        combine = datetime.combine
        year = self.now.year
        while True:
            year += 1
            for day in self.cron._matching_days(year):
                for t in self.times:
                    yield combine(day, t)

    def _iter_this_year(self) -> Iterator[datetime]:
        combine = datetime.combine
        today = self.now.date()

        month_part: MonthPart = self.cron.month
        for day in month_part.matching_dates(self.now.year, self.now.month):
            if day == today:
                current_time = self.now.time()
                for t in self.times:
                    if t > current_time:
                        yield combine(day, t)
            elif day > today:
                for t in self.times:
                    yield combine(day, t)

        for month_num in range(self.now.month + 1, 13):
            for day in month_part.matching_dates(self.now.year, month_num):
                for t in self.times:
                    yield combine(day, t)


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


# region Date/Time Helpers


def _dates(year: int, month: int, *, start: int = 1, reverse: bool = False) -> Iterator[date]:
    days = range(31, start - 1, -1) if reverse else range(start, 32)
    for day in days:
        try:
            yield date(year, month, day)
        except ValueError:  # day out of range for month
            if not reverse:
                break  # skip remaining days which will also be out of range


def _last_day_of_month(dt: date | datetime) -> date:
    for day in range(31, 27, -1):
        try:
            return date(dt.year, dt.month, day)
        except ValueError:  # day out of range for month
            pass
    raise CronError(f'Unexpected date={dt.isoformat()}')


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
