
import logging
from copy import deepcopy
from typing import Any, Dict, Optional, Iterator

import xmltodict
from win32com.client import DispatchBaseClass

from ..libs.taskschd import taskschd
from .constants import XML_ATTRS, CLSID_ENUM_MAP, RUN_RESULT_CODE_MAP
from .win_cron import WinCronSchedule

__all__ = ['walk_folders', 'scheduler_obj_as_dict', 'task_as_dict', 'norm_path', 'path_and_name']
log = logging.getLogger(__name__)


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
        # TODO: Replace with the proper objects?
        actions = xml['Actions']
        if i == 0:
            if action := next((v for k, v in actions.items() if not k.startswith('@')), None):
                as_dict.update(action)
        else:
            raise ValueError(f'Unexpected {actions=!r} in task @ uri={xml["RegistrationInfo"]["URI"]!r}')

    return as_dict


def task_as_dict(task: taskschd.IRegisteredTask, summarize=False):
    log.debug(f'Processing task={task.Path}', extra={'color': 'cyan'})
    task_xml = xmltodict.parse(task.Xml)['Task']
    as_dict = scheduler_obj_as_dict(task, task_xml)
    for key in ('LastRunTime', 'NextRunTime'):
        as_dict[key] = as_dict[key].strftime('%Y-%m-%d %H:%M:%S')  # TZ is not set correctly

    return _summarize(as_dict) if summarize else as_dict


def walk_folders(folder: taskschd.ITaskFolder, hidden, recursive: bool = True) -> Iterator[taskschd.ITaskFolder]:
    yield folder
    for sub_path in folder.GetFolders(int(hidden)):
        if recursive:
            yield from walk_folders(sub_path, hidden)
        else:
            yield sub_path


def _run_result_str(result: int):
    if result < 0:
        result += 2 ** 32
    code_str = hex(result)
    try:
        return f'{RUN_RESULT_CODE_MAP[result]} ({code_str})'
    except KeyError:
        return f'({code_str})'


def _summarize(task_dict):
    definition = task_dict['Definition']
    reg_info = definition['RegistrationInfo']
    actions = definition['Actions']['values']
    return {
        'Location': task_dict['Path'],
        'Status': task_dict['State'],
        'LastRun': task_dict['LastRunTime'],
        'NextRun': task_dict['NextRunTime'],
        'LastResult': _run_result_str(task_dict['LastTaskResult']),
        'Enabled': task_dict['Enabled'],
        'Author': reg_info['Author'],
        'Description': reg_info['Description'],
        'RunAs': definition['Principal']['UserId'],
        'Actions': actions,
        'Triggers': definition['Triggers']
        # 'Schedule': [f'{t["Type"]}: {t["cron"]}' for t in definition['Triggers']['values']],
        # 'Cron': list(filter(None, (t['cron'] for t in definition['Triggers']['values']))),
    }


def norm_path(path: Optional[str]):
    if not path:
        return '\\'
    return '\\' + path if not path.startswith('\\') else path


def path_and_name(path: Optional[str]):
    path, name = norm_path(path).rsplit('\\', 1)
    return norm_path(path), name
