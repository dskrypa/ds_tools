from __future__ import annotations

import logging
import re
from datetime import datetime
from functools import cached_property
from typing import Iterator

from ...utils.cron import ExtCronSchedule, TimePart, L

try:
    from ..com.utils import com_repr
except ImportError:  # Missing optional dependency or not on Windows
    com_repr = repr

from .exceptions import UnsupportedTriggerInterval

__all__ = ['WinCronSchedule']
log = logging.getLogger(__name__)
CronDict = dict[int | str, bool]

INTERVAL_PAT = re.compile(r'PT?(?:(?P<day>\d+)D)?(?:(?P<hour>\d+)H)?(?:(?P<minute>\d+)M)?(?:(?P<second>\d+)S)?')
# TODO: Expand the types of Windows triggers that can be created from a given WinCronSchedule [only supports Time now]


class WinCronSchedule(ExtCronSchedule):
    _start: datetime | None = None

    def __init__(self, cron_str: str = None):
        if cron_str:
            super().__init__(cron_str)
        else:
            self.reset()

    @classmethod
    def from_trigger(cls, trigger) -> WinCronSchedule:
        # log.debug(f'Converting trigger={com_repr(trigger)} to cron')
        self = cls()
        self._set_start(_parse_start(trigger))

        match trigger.Type:
            case 0:  # IEventTrigger
                self._set_from_interval(trigger.Repetition.Interval)  # interval = at most this frequently on the event?
            case 1:  # ITimeTrigger
                self._set_from_interval(trigger.Repetition.Interval)
            case 2:  # IDailyTrigger
                interval = trigger.DaysInterval
                self.day.set_all((i for i in range(1, 32) if i % interval == 0), True)
            # case 3:  # IWeeklyTrigger
            #     # week = CronPart(6, min=1, special='L')  # Week of month; L = last
            #     self.dow.set_intervals(_unpack(trigger.DaysOfWeek, 7))
            #     interval = trigger.WeeksInterval
            #     self.week.set_intervals({i: i == interval for i in range(1, 7)})
            case 4:  # IMonthlyTrigger
                self.day.set_all(_iter_unpack(trigger.DaysOfMonth, 31, 1), True)
                self.day['L'] = trigger.RunOnLastDayOfMonth
                self.month.set_all(_iter_unpack(trigger.MonthsOfYear, 12, 1), True)
            case 5:  # IMonthlyDOWTrigger
                self.month.set_all(_iter_unpack(trigger.MonthsOfYear, 12, 1), True)
                if trigger.WeeksOfMonth & 15 == 15:  # bit-packed 4x True (technically supports 6x)
                    self.dow.set_all(_iter_unpack(trigger.DaysOfWeek, 7), True)
                else:
                    self.dow.arr.setall(False)
                    for week in _weeks(trigger):
                        for day in _iter_unpack(trigger.DaysOfWeek, 7):
                            self.dow.set_day_in_week(week, day)
            case 6:  # IIdleTrigger
                self._set_from_interval(trigger.Repetition.Interval)  # interval = at most this frequently on idle?
            # case 7:  # IRegistrationTrigger  # Does not seem convertible
            #     pass
            case 8:  # IBootTrigger
                self._set_from_interval(trigger.Repetition.Interval)  # interval = at most this frequently on boot?
            case 9:  # ILogonTrigger
                self._set_from_interval(trigger.Repetition.Interval)
            # case 11:  # ISessionStateChangeTrigger  # Does not seem convertible
            #     pass
            case _:
                raise ValueError(f'Unexpected trigger={com_repr(trigger)}')

        return self

    @cached_property
    def start(self) -> datetime:
        if self._start:
            return self._start
        return datetime.now().replace(
            second=min(self.second), minute=min(self.minute), hour=min(self.hour), microsecond=0
        )

    def _set_start(self, start: datetime | None):
        if start is not None:
            self._start = start
            self.second.replace(start.second, True)
            self.minute.replace(start.minute, True)
            self.hour.replace(start.hour, True)

    def _set_from_interval(self, interval: str):
        if interval == 'PT0M':  # every second
            self.reset()
            return
        elif not (m := INTERVAL_PAT.match(interval)):
            raise UnsupportedTriggerInterval(f'Unexpected {interval=}')

        parts = {k: v for k, v in m.groupdict().items() if v}
        if not parts:
            raise UnsupportedTriggerInterval(f'Unsupported {interval=} - no time divisions found')
        elif len(parts) > 1:
            raise UnsupportedTriggerInterval(f'Unsupported {interval=} - contains multiple time divisions')

        # keys = ('day', 'hour', 'minute', 'second')
        key, value = parts.popitem()
        value = int(value)
        freq = getattr(self, key)
        start_val = getattr(self._start, key, 0)
        # log.debug(f'Updating {freq=!r} for {interval=!r} with {start_val=!r} and {value=!r}')
        for i in freq:
            freq[i] = (i - start_val) % value == 0

    def _interval_repr(self, freq: TimePart, attr: str, bigger: tuple[str, ...]):
        if freq.arr.all():
            return ''

        suffix = attr.upper()[0]
        enabled = set(freq)
        if len(enabled) == 1 and next(iter(enabled)) == getattr(self.start, attr):
            if all(getattr(self, b).arr.all() for b in bigger):
                # if all(all(getattr(self, f'_{b}').values()) for b in bigger):
                return f'1{bigger[0].upper()[0]}'
            return ''

        if step_str := freq._get_step_str():
            return f'{step_str.split("/", 1)[1]}{suffix}'

        diffs = set()
        last = None
        for value in sorted(enabled, reverse=True):
            if last is not None:
                # noinspection PyUnresolvedReferences
                diffs.add(last - value)
            last = value

        if len(diffs) == 1:
            return f'{next(iter(diffs))}{suffix}'
        raise ValueError(f'{self!r} cannot be represented using a Windows scheduler interval')

    @cached_property
    def interval(self):
        parts = ['P']
        attrs = (
            (self.day, 'day', ('month', 'dow')),
            (self.hour, 'hour', ('day', 'month', 'dow')),
            (self.minute, 'minute', ('hour', 'day', 'month', 'dow')),
            (self.second, 'second', ('minute', 'hour', 'day', 'month', 'dow')),
        )
        for prop, attr, bigger in attrs:
            rep = self._interval_repr(prop, attr, bigger)
            if rep and attr != 'day' and len(parts) == 1:
                parts.append('T')
            parts.append(rep)

        return ''.join(parts)


def _unpack(packed: int, n: int, offset: int = 0) -> CronDict:
    return {i + offset: bool(packed & (1 << i)) for i in range(n)}


def _iter_unpack(packed: int, n: int, offset: int = 0) -> Iterator[int]:
    for i in range(n):
        if packed & (1 << i):
            yield i + offset


def _weeks(trigger) -> Iterator[int | L]:
    yield from _iter_unpack(trigger.WeeksOfMonth, 6, 1)
    if trigger.RunOnLastWeekOfMonth:
        yield 'L'  # noqa


def _parse_start(trigger) -> datetime | None:
    try:
        start = trigger.StartBoundary
    except AttributeError:
        return None

    if not start:  # It may be an empty string
        return None

    try:
        return datetime.strptime(start, '%Y-%m-%dT%H:%M:%S')
    except ValueError:
        try:
            return datetime.strptime(start, '%Y-%m-%dT%H:%M:%S%z')
        except ValueError:
            raise RuntimeError(f'Unexpected time format for {start=}')
