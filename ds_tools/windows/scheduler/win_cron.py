
import logging
import re
from datetime import datetime
from functools import cached_property
from typing import Optional, Dict, Tuple, Union, Iterable

from ..com.utils import com_repr

__all__ = ['WinCronSchedule']
log = logging.getLogger(__name__)
CronDict = Dict[Union[int, str], bool]

INTERVAL_PAT = re.compile(r'PT?(?:(?P<day>\d+)D)?(?:(?P<hour>\d+)H)?(?:(?P<minute>\d+)M)?(?:(?P<second>\d+)S)?')
# TODO: Expand the types of Windows triggers that can be created from a given WinCronSchedule [only supports Time now]


class WinCronSchedule:
    def __init__(self, start: Optional[datetime] = None):
        self._start = start
        self._init()

    def _init(self):
        # TODO: These may be easier to handle as slightly more complex descriptors
        self._second = {i: True for i in range(60)}
        self._minute = {i: True for i in range(60)}
        self._hour = {i: True for i in range(24)}
        self._day = {i: True for i in range(1, 32)}
        self._month = {i: True for i in range(1, 13)}
        self._dow = {i: True for i in range(7)}  # 0-6; sunday = 0
        self._weeks = {i: True for i in range(1, 5)}

    @classmethod
    def from_cron(cls, cron_str: str) -> 'WinCronSchedule':
        # {second} {minute} {hour} {day_of_month} {month} {day_of_week}
        self = cls()
        attrs = (self._second, self._minute, self._hour, self._day, self._month, self._dow)
        for i, (attr, part) in enumerate(zip(attrs, cron_str.split())):
            self._set(attr, part, i)
        return self

    @classmethod
    def from_trigger(cls, trigger) -> 'WinCronSchedule':
        if start := getattr(trigger, 'StartBoundary', None):
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
            self._day = {i: i % interval == 0 for i in range(1, 32)}
        elif trigger.Type == 3:  # IWeeklyTrigger
            self._dow = _unpack(trigger.DaysOfWeek, 7)
            interval = trigger.WeeksInterval
            self._weeks = {i: i == interval for i in range(1, 6)}
        elif trigger.Type == 4:  # IMonthlyTrigger
            self._day = _unpack(trigger.DaysOfMonth, 31, 1)
            self._day['L'] = trigger.RunOnLastDayOfMonth
            self._month = _unpack(trigger.MonthsOfYear, 12, 1)
        elif trigger.Type == 5:  # IMonthlyDOWTrigger
            self._dow = _unpack(trigger.DaysOfWeek, 7)
            self._month = _unpack(trigger.MonthsOfYear, 12, 1)
            self._weeks = _unpack(trigger.WeeksOfMonth, 4, 1)
            self._weeks['L'] = trigger.RunOnLastWeekOfMonth
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
            self._init()
            return
        elif not (m := INTERVAL_PAT.match(interval)):
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
        if dt_obj is not None:
            self._second = {i: i == dt_obj.second for i in range(60)}
            self._minute = {i: i == dt_obj.minute for i in range(60)}
            self._hour = {i: i == dt_obj.hour for i in range(24)}

    def _set(self, freq: CronDict, part: str, pos: int):
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
            parts = set(part.split(','))
            if 'L' in parts:
                if pos == 3:  # day
                    freq['L'] = True
                    parts.remove('L')
                else:
                    raise ValueError(f'Invalid cron schedule {part=!r} in {pos=}')
            elif pos == 5:  # dow#week
                _parts = set()
                weeks = set()
                for p in parts:
                    if '#' in p:
                        val, week = p.split('#')
                        _parts.add(val)
                        if week == 'L':
                            self._weeks['L'] = True
                        else:
                            try:
                                week = int(week)
                            except (TypeError, ValueError):
                                raise ValueError(f'Invalid cron schedule {part=!r} in {pos=}')
                            else:
                                if 1 <= week <= 4:
                                    weeks.add(week)
                                else:
                                    raise ValueError(f'Invalid cron schedule {part=!r} in {pos=}')

                if weeks:
                    for week in range(1, 5):
                        self._weeks[week] = week in weeks
                parts = _parts

            vals = set()
            for p in parts:
                if '-' in p:
                    try:
                        a, b = map(int, p.split('-'))
                    except (TypeError, ValueError):
                        raise ValueError(f'Invalid cron schedule {part=!r} in {pos=}')
                    if a >= b:
                        raise ValueError(f'Invalid cron schedule {part=!r} in {pos=}')
                    vals.update(range(a, b + 1))
                else:
                    try:
                        vals.add(int(p))
                    except (TypeError, ValueError):
                        raise ValueError(f'Invalid cron schedule {part=!r} in {pos=}')

            for k in freq:
                if k != 'L':
                    freq[k] = k in vals

    def __repr__(self):
        return f'<{self.__class__.__name__}[{self}]>'

    def __str__(self):
        # {second} {minute} {hour} {day_of_month} {month} {day_of_week}
        return ' '.join((self.second, self.minute, self.hour, self.day, self.month, self.dow))

    def _cron_repr(self, freq: CronDict, dow: bool = False):
        if all(freq.values()):
            return '*'

        last = freq.get('L')
        enabled = {k for k, v in freq.items() if v and k != 'L'}
        if not enabled:
            if last:
                return 'L'
            raise ValueError('Unexpected state')

        if dow and not all(v for k, v in self._weeks.items() if k != 'L'):
            weeks = sorted([str(w) for w, v in self._weeks.items() if v])
            return ','.join(f'{v}#{w}' for v in sorted(enabled) for w in weeks)

        if not last:
            for divisor in range(2, len(freq) // 2 + 1):
                divisible = {k for k in freq if isinstance(k, int) and k % divisor == 0}
                if divisible == enabled:
                    # log.warning(f'{divisible=}.intersection({enabled=}) == divisible ({divisor=})')
                    return f'*/{divisor}'

        collapsed = collapse(sorted(enabled))
        return f'{collapsed},L' if last else collapsed

    def _interval_repr(self, freq: CronDict, attr: str, bigger: Tuple[str, ...]):
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


def _unpack(packed: int, n: int, offset: int = 0) -> CronDict:
    return {i + offset: bool(packed & (1 << i)) for i in range(n)}


def collapse(values: Iterable[int]):
    ranges = []
    last = None
    for value in values:
        if last is None:
            ranges.append((value, value))
        elif value - last == 1:
            ranges[-1] = (ranges[-1][0], value)
        else:
            ranges.append((value, value))

        last = value

    return ','.join(str(a) if a == b else f'{a}-{b}' for a, b in ranges)
