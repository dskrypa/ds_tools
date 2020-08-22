
import logging
import re
from copy import deepcopy
from datetime import datetime
from typing import Optional, Mapping, Any, Dict

import xmltodict
# from win32com import client
from win32com.client import DispatchBaseClass
# from win32comext.taskscheduler import taskscheduler

from .constants import XML_ATTRS, CLSID_ENUM_MAP, DAY_NAME_NUM_MAP, MONTH_NAME_NUM_MAP

__all__ = ['walk_paths', 'scheduler_obj_as_dict', 'task_as_dict']
log = logging.getLogger(__name__)

INTERVAL_PAT = re.compile(r'PT?(?:(?P<day>\d+)D)?(?:(?P<hour>\d+)H)?(?:(?P<minute>\d+)M)?(?:(?P<second>\d+)S)?')
XMLNS_PAT = re.compile(r'\s?xmlns="[^"]+"')


def normalize_triggers(triggers: Dict[str, Any]):
    normalized = []
    extra_keys = ('EndBoundary', 'ExecutionTimeLimit', 'Delay', 'RandomDelay')
    for key, value in triggers.items():
        log.debug(f'Processing trigger with {key=} {value=}')
        if isinstance(value, list):
            for entry in value:
                _entry = deepcopy(entry)  # type: Dict[str, Dict[str, Any]]
                norm = {k: v for k in extra_keys if (v := _entry.pop(k, None))}
                start = norm['start'] = _entry.pop('StartBoundary', None)
                trigger_type, schedule = _entry.popitem()
                norm['type'] = trigger_type
                try:
                    norm['cron'] = WinCronSchedule.from_trigger(trigger_type, schedule, start)
                except ValueError:
                    try:
                        norm['cron'] = str({k: dict(v) for k, v in schedule.items()})
                    except Exception:
                        norm['cron'] = str(schedule)

                normalized.append(norm)
        elif value is None:
            normalized.append({'type': key, 'cron': None, 'start': None})
        else:
            _entry = deepcopy(value)
            trigger_type = _entry.pop('@id', key)
            norm = {k: v for k in extra_keys if (v := _entry.pop(k, None))}
            start = norm['start'] = _entry.pop('StartBoundary', None)
            norm['type'] = trigger_type
            try:
                norm['cron'] = WinCronSchedule.from_trigger(trigger_type, _entry, start)
            except ValueError:
                try:
                    norm['cron'] = str({k: dict(v) for k, v in _entry.items()})
                except Exception:
                    norm['cron'] = str(_entry)
            normalized.append(norm)

    return normalized


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
    def from_cron(cls, cron_str: str):
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

    def _repr(self, freq: Mapping[int, bool], dow: bool = False):
        if all(freq.values()):
            return '*'

        on_vals = {k for k, v in freq.items() if v}
        if dow and not all(v for k, v in self._weeks.items()):
            weeks = sorted([w for w, v in self._weeks.items() if v])
            return ','.join(f'{v}#{w}' for v in sorted(on_vals) for w in weeks)

        for divisor in range(2, len(freq) // 2 + 1):
            divisible = {k for k in freq if k % divisor == 0}
            if divisible.intersection(on_vals) == divisible:
                return f'*/{divisor}'

        return ','.join(str(k) for k, v in sorted(freq.items()) if v)

    @property
    def second(self):
        return self._repr(self._second)

    @property
    def minute(self):
        return self._repr(self._minute)

    @property
    def hour(self):
        return self._repr(self._hour)

    @property
    def day(self):
        return self._repr(self._day)

    @property
    def month(self):
        return self._repr(self._month)

    @property
    def dow(self):
        return self._repr(self._dow, True)


def scheduler_obj_as_dict(obj, xml, i=None):
    as_dict = {}
    clsid = str(obj.CLSID)
    # log.debug(f'Processing {clsid=} {obj=}')
    cls_enums = CLSID_ENUM_MAP.get(clsid) or {}
    for attr in obj._prop_map_get_:
        if attr not in XML_ATTRS:
            value = getattr(obj, attr)
            if isinstance(value, DispatchBaseClass):
                log.debug(f'Processing {value=} with clsid={value.CLSID} {i=}')
                if str(value.CLSID) == '{85DF5081-1B24-4F32-878A-D9D14DF4CB77}':  # ITriggerCollection
                    log.debug('Adding cron schedules...')
                    if triggers := xml['Triggers']:
                        value = normalize_triggers(triggers)
                    else:
                        value = []
                else:
                    _value = scheduler_obj_as_dict(value, xml)
                    try:
                        # noinspection PyTypeChecker
                        _value['values'] = [scheduler_obj_as_dict(v, xml, i) for i, v in enumerate(value)]
                    except TypeError:
                        pass
                    value = _value
            elif attr_enum := cls_enums.get(attr):
                value = attr_enum.get(value, value)

            as_dict[attr] = value

    # if clsid == '{09941815-EA89-4B5B-89E0-2A773801FAC3}':  # IEventTrigger
    #     pass
    if clsid == '{BAE54997-48B1-4CBE-9965-D6BE263EBEA4}' and i is not None:  # IAction
        # I couldn't figure out how to get the lib to give me IExecAction objects...
        actions = xml['Actions']
        if i == 0:
            if action := next((v for k, v in actions.items() if not k.startswith('@')), None):
                as_dict.update(action)
        else:
            raise ValueError(f'Unexpected {actions=!r} in task @ uri={xml["RegistrationInfo"]["URI"]!r}')

    return as_dict


def task_as_dict(task):
    log.debug(f'Processing task={task.Path}', extra={'color': 'cyan'})
    task_xml = xmltodict.parse(task.Xml)['Task']
    as_dict = scheduler_obj_as_dict(task, task_xml)
    for key in ('LastRunTime', 'NextRunTime'):
        as_dict[key] = as_dict[key].strftime('%Y-%m-%d %H:%M:%S')  # TZ is not set correctly

    return as_dict


def walk_paths(path, hidden, recursive: bool = True):
    yield path
    for sub_path in path.GetFolders(hidden):
        if recursive:
            yield from walk_paths(sub_path, hidden)
        else:
            yield sub_path
