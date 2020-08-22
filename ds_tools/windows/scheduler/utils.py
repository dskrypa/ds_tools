
import logging
import re
from collections import Counter
from datetime import datetime
from typing import Optional, Literal, Union, Mapping, Any, List, Dict
from xml.etree.ElementTree import XML, Element

import xmltodict
from win32com import client
from win32com.client import DispatchBaseClass
from win32comext.taskscheduler import taskscheduler

from .constants import XML_ATTRS, CLSID_ENUM_MAP, REPETITION_CODE_CRON_TUPLES

__all__ = ['walk_paths', 'scheduler_obj_as_dict', 'task_as_dict', 'as_cron']
log = logging.getLogger(__name__)

INTERVAL_PAT = re.compile(r'PT?(?:(?P<days>\d+)D)?(?:(?P<hours>\d+)H)?(?:(?P<min>\d+)M)?(?:(?P<sec>\d+)S)?')
XMLNS_PAT = re.compile(r'\s?xmlns="[^"]+"')
INTERVAL_MAX_VALUES = {'hours': 23, 'min': 59, 'sec': 59}


def interval_to_cron_parts(interval: str, trigger) -> List[Union[str, int]]:
    if interval == 'PT0M':
        return ['*', '*', '*', '*', '*', '*']
    if not (m := INTERVAL_PAT.match(interval)):
        raise ValueError(f'Unexpected {interval=!r}')
    parts = m.groupdict()

    keys = ('days', 'hours', 'min', 'sec')
    values = []
    found = False
    for key in keys:
        value = parts[key]
        try:
            value = int(value)
        except (TypeError, ValueError):
            values.append(1 if found else '*')
        else:
            found = True
            if value == 1:
                values.append('*')
            elif key == 'days' and value % 30 == 0:
                values.append(1)
                values.append(value // 30)
            elif (max_val := INTERVAL_MAX_VALUES[key]) and value > max_val:
                raise ValueError(f'Invalid {interval=!r} - {key}={value} > {max_val}')
            else:
                values.append(value)

    values.reverse()
    values += ['*'] * (6 - len(values))
    return values


def as_cron(trigger):
    start = datetime.strptime(trigger.StartBoundary, '%Y-%m-%dT%H:%M:%S')
    trigger_type = trigger.Type
    if trigger_type == 1:  # Time
        interval = trigger.Repetition.Interval
    elif trigger_type in (2, 3, 4):  # Daily, Weekly, Monthly
        interval = trigger.Repetition.Interval
    # elif trigger_type == 5:  # MonthlyDOW  # TODO: ???
    #     pass
    else:
        raise ValueError(f'Unable to convert {trigger=!r} to cron expression format')

    try:
        cron_parts = interval_to_cron_parts(interval)
    except ValueError as e:
        raise ValueError(f'Unable to convert {trigger=!r} to cron expression format') from e

    start_parts = (start.second, start.minute, start.hour, start.day, start.month, 1)
    out_parts = []
    for start_part, cron_part in zip(start_parts, cron_parts):
        if isinstance(cron_part, str):
            out_parts.append(cron_part)
        elif cron_part == 1:
            out_parts.append(str(start_part))
        # elif start_part % cron_part == 0:  # TODO: Calculate times for non-equally divided
        #     start_part = start_part or '*'
        #     out_parts.append(f'{start_part}/{cron_part}')
        else:
            start_part = start_part or '*'
            out_parts.append(f'{start_part}/{cron_part}')

    return ' '.join(out_parts)


class WinCronSchedule:
    def __init__(self):
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
    def from_triggers(cls, triggers: Mapping[str, Any]):
        raise NotImplementedError

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

    if clsid == '{09941815-EA89-4B5B-89E0-2A773801FAC3}':  # IEventTrigger

        try:
            as_dict['cron'] = as_cron(obj, )
        except ValueError:
            as_dict['cron'] = None
    elif clsid == '{BAE54997-48B1-4CBE-9965-D6BE263EBEA4}' and i is not None:  # IAction
        # I couldn't figure out how to get the lib to give me IExecAction objects...
        actions = xml['Actions']
        if i == 0:
            if action := next((v for k, v in actions.items() if not k.startswith('@')), None):
                as_dict.update(action)
        else:
            raise ValueError(f'Unexpected {actions=!r} in task @ uri={xml["RegistrationInfo"]["URI"]!r}')

    return as_dict


def task_as_dict(task):
    task_xml = xmltodict.parse(task.Xml)['Task']
    as_dict = scheduler_obj_as_dict(task, task_xml)

    # This is because I couldn't figure out how to get the lib to give me IExecAction objects...
    # as_dict['Definition']['Actions']['details'] = task_xml['Actions']

    return as_dict


def walk_paths(path, hidden, recursive: bool = True):
    yield path
    for sub_path in path.GetFolders(hidden):
        if recursive:
            yield from walk_paths(sub_path, hidden)
        else:
            yield sub_path
