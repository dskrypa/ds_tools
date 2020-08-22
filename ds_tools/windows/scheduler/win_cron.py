
import logging
import re
from datetime import datetime
from functools import cached_property
from typing import Optional, Mapping, Any, Dict, Tuple

from .constants import DAY_NAME_NUM_MAP, MONTH_NAME_NUM_MAP

__all__ = ['WinCronSchedule']
log = logging.getLogger(__name__)

INTERVAL_PAT = re.compile(r'PT?(?:(?P<day>\d+)D)?(?:(?P<hour>\d+)H)?(?:(?P<minute>\d+)M)?(?:(?P<second>\d+)S)?')


class WinCronSchedule:
    def __init__(self, start: Optional[datetime] = None):
        self._start = start
        self._init()

    def _init(self):
        self._second = {i: True for i in range(60)}
        self._minute = {i: True for i in range(60)}
        self._hour = {i: True for i in range(24)}
        self._day = {i: True for i in range(1, 31)}
        self._month = {i: True for i in range(1, 13)}
        self._dow = {i: True for i in range(7)}  # 0-6; sunday = 0
        self._weeks = {i: True for i in range(1, 6)}

    @classmethod
    def from_cron(cls, cron_str: str) -> 'WinCronSchedule':
        # {second} {minute} {hour} {day_of_month} {month} {day_of_week}
        self = cls()
        attrs = (self._second, self._minute, self._hour, self._day, self._month, self._dow)
        for i, (attr, part) in enumerate(zip(attrs, cron_str.split())):
            self._set(attr, part, i)
        return self

    @classmethod
    def from_trigger(cls, trigger_type: str, schedule: Dict[str, Any], start: Optional[str]) -> 'WinCronSchedule':
        if start:
            try:
                start = datetime.strptime(start, '%Y-%m-%dT%H:%M:%S')
            except ValueError:
                try:
                    start = datetime.strptime(start, '%Y-%m-%dT%H:%M:%S%z')
                except ValueError:
                    raise RuntimeError(f'Unexpected time format for {start=}')

        self = cls(start)
        if trigger_type == 'ScheduleByMonthDayOfWeek':
            self._set_time(start)
            for name, section in schedule.items():
                if name == 'DaysOfWeek':
                    enabled = {DAY_NAME_NUM_MAP[day] for day in section}
                    self._dow = {i: i in enabled for i in range(7)}
                elif name == 'Months':
                    enabled = {MONTH_NAME_NUM_MAP[month] for month in section}
                    self._month = {i: i in enabled for i in range(1, 13)}
                elif name == 'Weeks':
                    weeks = section['Week']
                    enabled = {int(weeks)} if isinstance(weeks, str) else set(map(int, weeks))
                    self._weeks = {i: i in enabled for i in range(1, 6)}
                else:
                    raise ValueError(f'Unexpected section={name!r} in type={trigger_type!r} {schedule=} {start=}')
        elif trigger_type in ('TriggerDaily', 'CalendarTrigger'):
            self._set_time(start)
            for name, section in schedule.items():
                if name == 'ScheduleByDay':
                    interval = int(section['DaysInterval'])
                    self._day = {i: i % interval == 0 for i in range(1, 31)}
                else:
                    raise ValueError(f'Unexpected section={name!r} in type={trigger_type!r} {schedule=} {start=}')
        elif trigger_type in ('TriggerUserLoggon', 'TimeTrigger'):  # sic
            self._set_time(start)
            for name, section in schedule.items():
                if name == 'Repetition':
                    self._set_from_interval(section['Interval'])
                else:
                    raise ValueError(f'Unexpected section={name!r} in type={trigger_type!r} {schedule=} {start=}')
        else:
            raise ValueError(f'Unexpected trigger type={trigger_type!r} for {schedule=} {start=}')

        return self

    def _set_from_interval(self, interval: str):
        if interval == 'PT0M':  # every second
            self._init()
            return
        if not (m := INTERVAL_PAT.match(interval)):
            raise ValueError(f'Unexpected {interval=!r}')

        parts = {k: v for k, v in m.groupdict().items() if v}
        if not parts:
            raise ValueError(f'Unsupported {interval=!r} - no time divisions found')
        elif len(parts) > 1:
            raise ValueError(f'Unsupported {interval=!r} - contains multiple time divisions')

        # keys = ('day', 'hour', 'minute', 'second')
        key, value = parts.popitem()
        value = int(value)
        freq = getattr(self, f'_{key}')
        start_val = getattr(self._start, key, 0)
        for i in freq:
            freq[i] = (i - start_val) % value == 0

    def _set_time(self, dt_obj: datetime):
        self._second = {i: i == dt_obj.second for i in range(60)}
        self._minute = {i: i == dt_obj.minute for i in range(60)}
        self._hour = {i: i == dt_obj.hour for i in range(24)}

    def _set(self, freq: Dict[int, bool], part: str, pos: int):
        if part == '*':
            for k in freq:
                freq[k] = True
        elif '/' in part:
            a, divisor = part.split('/', 1)
            if a != '*' or not divisor.isnumeric():
                raise ValueError(f'Invalid cron schedule {part=!r} in {pos=}')
            divisor = int(divisor)
            for k in freq:
                freq[k] = k % divisor == 0
        else:
            try:
                vals = set(map(int, part.split(',')))
            except (ValueError, TypeError):
                if pos != 5:
                    raise ValueError(f'Invalid cron schedule {part=!r} in {pos=}')
                vals = set()
                weeks = set()
                for p in part.split(','):
                    try:
                        val, week = map(int, p.split('#'))
                    except ValueError:
                        try:
                            val = int(p)
                        except (TypeError, ValueError):
                            raise ValueError(f'Invalid cron schedule {part=!r} in {pos=}')
                    else:
                        if week in self._weeks:
                            weeks.add(week)
                        else:
                            raise ValueError(f'Invalid cron schedule {part=!r} in {pos=}')
                    vals.add(val)
                for week in self._weeks:
                    self._weeks[week] = week in weeks

            for k in freq:
                freq[k] = k in vals

    def __repr__(self):
        return f'<{self.__class__.__name__}[{self}]>'

    def __str__(self):
        # {second} {minute} {hour} {day_of_month} {month} {day_of_week}
        return ' '.join((self.second, self.minute, self.hour, self.day, self.month, self.dow))

    def _cron_repr(self, freq: Mapping[int, bool], dow: bool = False):
        if all(freq.values()):
            return '*'

        enabled = {k for k, v in freq.items() if v}
        if dow and not all(v for k, v in self._weeks.items()):
            weeks = sorted([w for w, v in self._weeks.items() if v])
            return ','.join(f'{v}#{w}' for v in sorted(enabled) for w in weeks)

        for divisor in range(2, len(freq) // 2 + 1):
            divisible = {k for k in freq if k % divisor == 0}
            if divisible.intersection(enabled) == divisible:
                return f'*/{divisor}'

        return ','.join(str(k) for k, v in sorted(freq.items()) if v)

    def _interval_repr(self, freq: Mapping[int, bool], attr: str, bigger: Tuple[str, ...]):
        if all(freq.values()):
            return ''

        suffix = attr.upper()[0]
        enabled = {k for k, v in freq.items() if v}
        if len(enabled) == 1 and next(iter(enabled)) == getattr(self.start, attr):
            if all(all(getattr(self, f'_{b}').values()) for b in bigger):
                return f'1{bigger[0].upper()[0]}'
            return ''

        for divisor in range(2, len(freq) // 2 + 1):
            divisible = {k for k in freq if k % divisor == 0}
            if divisible.intersection(enabled) == divisible:
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
    def start(self) -> datetime:
        if self._start:
            return self._start
        dt = datetime.now().replace(
            second=min(k for k, v in self._second.items() if v),
            minute=min(k for k, v in self._minute.items() if v),
            hour=min(k for k, v in self._hour.items() if v),
            microsecond=0,
        )
        return dt

    @cached_property
    def second(self):
        return self._cron_repr(self._second)

    @cached_property
    def minute(self):
        return self._cron_repr(self._minute)

    @cached_property
    def hour(self):
        return self._cron_repr(self._hour)

    @cached_property
    def day(self):
        return self._cron_repr(self._day)

    @cached_property
    def month(self):
        return self._cron_repr(self._month)

    @cached_property
    def dow(self):
        return self._cron_repr(self._dow, True)

    @cached_property
    def interval(self):
        parts = ['P']
        attrs = (
            (self._day, 'day', ('month', 'dow')),
            (self._hour, 'hour', ('day', 'month', 'dow')),
            (self._minute, 'minute', ('hour', 'day', 'month', 'dow')),
            (self._second, 'second', ('minute', 'hour', 'day', 'month', 'dow')),
        )
        for prop, attr, bigger in attrs:
            rep = self._interval_repr(prop, attr, bigger)
            if rep and attr != 'day' and len(parts) == 1:
                parts.append('T')
            parts.append(rep)

        return ''.join(parts)
