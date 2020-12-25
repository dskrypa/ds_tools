
import logging
from typing import Optional, Iterator

# noinspection PyUnresolvedReferences
from pywintypes import com_error
from win32com.client import DispatchBaseClass

from ..com.enums import ComClassEnum
from ..com.exceptions import IterationNotSupported
from ..com.utils import com_repr, com_iter
from ..libs.taskschd import taskschd
from .constants import XML_ATTRS, CLSID_ENUM_MAP, RUN_RESULT_CODE_MAP, DAY_LIST, MONTH_LIST
from .exceptions import UnsupportedTriggerInterval
from .win_cron import WinCronSchedule

__all__ = ['walk_folders', 'scheduler_obj_as_dict', 'task_as_dict', 'norm_path', 'path_and_name']
log = logging.getLogger(__name__)


def scheduler_obj_as_dict(obj, i=None, parent=None):
    as_dict = {}
    clsid = str(obj.CLSID)
    parent_clsid = str(parent.CLSID) if parent is not None else None
    log.debug(f'Processing {clsid=} {obj=}')
    cls_enums = CLSID_ENUM_MAP.get(clsid) or {}
    child_enum = ComClassEnum.get_child_class(parent_clsid)
    enum_attr = child_enum._attr if child_enum else None
    for attr in obj._prop_map_get_:
        if attr not in XML_ATTRS:
            value = getattr(obj, attr)
            if isinstance(value, DispatchBaseClass):
                log.debug(f'Processing {value=} with clsid={value.CLSID} {i=}')
                _value = scheduler_obj_as_dict(value)
                try:
                    # noinspection PyTypeChecker
                    _value['values'] = [scheduler_obj_as_dict(v, i, value) for i, v in enumerate(com_iter(value))]
                except IterationNotSupported:
                    pass
                value = _value
            elif attr_enum := cls_enums.get(attr):
                value = attr_enum.get(value, value)
            elif enum_attr == attr == 'Type':
                try:
                    value = child_enum.for_num(value).cls.__name__
                except ValueError as e:  # TASK_TRIGGER_CUSTOM_TRIGGER_01 has no custom class
                    log.debug(e)

            as_dict[attr] = value

    if parent_clsid == '{85DF5081-1B24-4F32-878A-D9D14DF4CB77}':  # ITriggerCollection
        log.debug(f'Processing trigger with {clsid=} {i=}')
        try:
            as_dict['cron'] = WinCronSchedule.from_trigger(obj)
        except Exception as e:
            trace = not isinstance(e, UnsupportedTriggerInterval)
            log.debug(
                f'Error processing cron schedule for {com_repr(obj)}: {e}', extra={'color': 'red'}, exc_info=trace
            )
            as_dict['cron'] = com_repr(obj, True)

    return as_dict


def task_as_dict(task: taskschd.IRegisteredTask, summarize=False):
    log.debug(f'Processing task={task.Path}', extra={'color': 'cyan'})
    # task_xml = xmltodict.parse(task.Xml)['Task']
    as_dict = scheduler_obj_as_dict(task)
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
        'Triggers': definition['Triggers']['values']
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


def unpack_days(packed: int, as_str=True):
    return [day if as_str else i for i, day in enumerate(DAY_LIST) if packed & (1 << i)]


def unpack_months(packed: int, as_str=True):
    return [month if as_str else i for i, month in enumerate(MONTH_LIST[1:]) if packed & (1 << i)]
