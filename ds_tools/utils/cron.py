"""
Utilities for parsing and interpreting crontab schedules

:author: Doug Skrypa
"""

import logging
from datetime import datetime
from functools import cached_property
from typing import Optional, Dict, Union, Iterable

__all__ = ['CronSchedule']
log = logging.getLogger(__name__)
CronDict = Dict[Union[int, str], bool]


class CronSchedule:
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
    def from_cron(cls, cron_str: str) -> 'CronSchedule':
        # {second} {minute} {hour} {day_of_month} {month} {day_of_week}
        self = cls()
        attrs = (self._second, self._minute, self._hour, self._day, self._month, self._dow)
        for i, (attr, part) in enumerate(zip(attrs, cron_str.split())):
            self._set(attr, part, i)
        return self

    def _set_time(self, dt_obj: datetime):
        if dt_obj is not None:
            self._second = {i: i == dt_obj.second for i in range(60)}
            self._minute = {i: i == dt_obj.minute for i in range(60)}
            self._hour = {i: i == dt_obj.hour for i in range(24)}

    def _set(self, freq: CronDict, part: str, pos: int):
        # log.debug(f'Processing {pos=} {part=!r}')
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
                    else:
                        _parts.add(p)

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
