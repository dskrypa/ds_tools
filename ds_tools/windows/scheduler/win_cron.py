
import logging
import re
from datetime import datetime
from functools import cached_property
from typing import Dict, Tuple, Union

from bitarray import bitarray

from ...utils.cron import CronSchedule, TimePart

try:
    from ..com.utils import com_repr
except ImportError:  # Missing optional dependency or not on Windows
    com_repr = repr

from .exceptions import UnsupportedTriggerInterval

__all__ = ['WinCronSchedule']
log = logging.getLogger(__name__)
CronDict = Dict[Union[int, str], bool]

INTERVAL_PAT = re.compile(r'PT?(?:(?P<day>\d+)D)?(?:(?P<hour>\d+)H)?(?:(?P<minute>\d+)M)?(?:(?P<second>\d+)S)?')
# TODO: Expand the types of Windows triggers that can be created from a given WinCronSchedule [only supports Time now]


def _unpack(packed: int, n: int, offset: int = 0) -> CronDict:
    return {i + offset: bool(packed & (1 << i)) for i in range(n)}


class WinCronSchedule(CronSchedule):
    @classmethod
    def from_trigger(cls, trigger) -> 'WinCronSchedule':
        # log.debug(f'Converting trigger={com_repr(trigger)} to cron')
        if start := getattr(trigger, 'StartBoundary', None) or None:  # May be an empty string
            try:
                start = datetime.strptime(start, '%Y-%m-%dT%H:%M:%S')
            except ValueError:
                try:
                    start = datetime.strptime(start, '%Y-%m-%dT%H:%M:%S%z')
                except ValueError:
                    raise RuntimeError(f'Unexpected time format for {start=}')

        self = cls(start)
        self._set_time(start)
        if trigger.Type == 0:  # IEventTrigger
            self._set_from_interval(trigger.Repetition.Interval)  # interval = at most this frequently on the event?
        elif trigger.Type == 1:  # ITimeTrigger
            self._set_from_interval(trigger.Repetition.Interval)
        elif trigger.Type == 2:  # IDailyTrigger
            interval = trigger.DaysInterval
            self.day.set_intervals({i: i % interval == 0 for i in range(1, 32)})
        elif trigger.Type == 3:  # IWeeklyTrigger
            self.dow.set_intervals(_unpack(trigger.DaysOfWeek, 7))
            interval = trigger.WeeksInterval
            self.week.set_intervals({i: i == interval for i in range(1, 7)})
        elif trigger.Type == 4:  # IMonthlyTrigger
            self.day.set_intervals(_unpack(trigger.DaysOfMonth, 31, 1))
            self.day['L'] = trigger.RunOnLastDayOfMonth
            self.month.set_intervals(_unpack(trigger.MonthsOfYear, 12, 1))
        elif trigger.Type == 5:  # IMonthlyDOWTrigger
            self.dow.set_intervals(_unpack(trigger.DaysOfWeek, 7))
            self.month.set_intervals(_unpack(trigger.MonthsOfYear, 12, 1))
            self.week.set_intervals(_unpack(trigger.WeeksOfMonth, 6, 1))
            self.week['L'] = trigger.RunOnLastWeekOfMonth
        elif trigger.Type == 6:  # IIdleTrigger
            self._set_from_interval(trigger.Repetition.Interval)  # interval = at most this frequently on idle?
        # elif trigger.Type == 7:  # IRegistrationTrigger  # Does not seem convertible
        #     pass
        elif trigger.Type == 8:  # IBootTrigger
            self._set_from_interval(trigger.Repetition.Interval)  # interval = at most this frequently on boot?
        elif trigger.Type == 9:  # ILogonTrigger
            self._set_from_interval(trigger.Repetition.Interval)
        # elif trigger.Type == 11:  # ISessionStateChangeTrigger  # Does not seem convertible
        #     pass
        else:
            raise ValueError(f'Unexpected trigger={com_repr(trigger)}')
        return self

    def _set_from_interval(self, interval: str):
        if interval == 'PT0M':  # every second
            self.reset()
            return
        elif not (m := INTERVAL_PAT.match(interval)):
            raise UnsupportedTriggerInterval(f'Unexpected {interval=!r}')

        parts = {k: v for k, v in m.groupdict().items() if v}
        if not parts:
            raise UnsupportedTriggerInterval(f'Unsupported {interval=!r} - no time divisions found')
        elif len(parts) > 1:
            raise UnsupportedTriggerInterval(f'Unsupported {interval=!r} - contains multiple time divisions')

        # keys = ('day', 'hour', 'minute', 'second')
        key, value = parts.popitem()
        value = int(value)
        freq = getattr(self, key)
        start_val = getattr(self._start, key, 0)
        # log.debug(f'Updating {freq=!r} for {interval=!r} with {start_val=!r} and {value=!r}')
        for i in freq:
            freq[i] = (i - start_val) % value == 0

    def _interval_repr(self, freq: TimePart, attr: str, bigger: Tuple[str, ...]):
        arr = freq.arr
        if arr.all():
            return ''

        suffix = attr.upper()[0]
        enabled = set(freq)
        if len(enabled) == 1 and next(iter(enabled)) == getattr(self.start, attr):
            if all(getattr(self, b).arr.all() for b in bigger):
                # if all(all(getattr(self, f'_{b}').values()) for b in bigger):
                return f'1{bigger[0].upper()[0]}'
            return ''

        for divisor in range(2, len(arr) // 2 + 1):
            divisible = bitarray(len(arr))
            divisible.setall(False)
            divisible[::divisor] = True
            if divisible == arr:
                return f'{divisor}{suffix}'

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
