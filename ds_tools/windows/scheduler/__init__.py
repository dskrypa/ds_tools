"""
Library for working with the Windows Task Scheduler

:author: Doug Skrypa
"""

import re
from xml.etree.ElementTree import XML
from functools import cached_property
from typing import Optional, Literal, Union

from win32com import client
from win32com.client import DispatchBaseClass

from .constants import XML_ATTRS, TASK_STATES, CLSID_ENUM_MAP

__all__ = ['Scheduler', 'Hidden']
Hidden = Union[bool, Literal[0, 1]]
XMLNS_PAT = re.compile(r'\s?xmlns="[^"]+"')


class Scheduler:
    @cached_property
    def _scheduler(self):
        service = client.Dispatch('Schedule.Service')
        service.Connect()
        return service

    def walk_paths(self, path: Optional[str] = '\\', hidden: Hidden = True, recursive: bool = True):
        hidden = int(hidden)
        root = self._scheduler.GetFolder(path)
        yield from _walk_paths(root, hidden, recursive)

    def get_tasks(self, path: Optional[str] = '\\', hidden: Hidden = True, recursive=True):
        hidden = int(hidden)
        tasks = []
        if recursive:
            # noinspection PyTypeChecker
            for path in self.walk_paths(path, hidden, recursive):
                tasks.extend(path.GetTasks(hidden))
        else:
            root = self._scheduler.GetFolder(path)
            tasks.extend(root.GetTasks(hidden))
        return tasks

    def get_tasks_dict(self, *args, summarize=False, **kwargs):
        tasks = self.get_tasks(*args, **kwargs)
        tasks_dict = {task.Name: _task_as_dict(task) for task in tasks}
        if summarize:
            summarized = {}
            for name, task in tasks_dict.items():
                definition = task['Definition']
                reg_info = definition['RegistrationInfo']
                actions = definition['Actions']['details']
                summarized[name] = {
                    'Location': task['Path'],
                    'Status': task['State'],
                    'LastRun': task['LastRunTime'],
                    'NextRun': task['NextRunTime'],
                    'LastResult': task['LastTaskResult'],
                    'Enabled': task['Enabled'],
                    'Author': reg_info['Author'],
                    'Description': reg_info['Description'],
                    'RunAs': definition['Principal']['UserId'],
                    'Actions': actions
                }
            return summarized
        else:
            return tasks_dict


def _task_as_dict(task):
    as_dict = _as_dict(task)
    # This is because I couldn't figure out how to get the lib to give me IExecAction objects...
    xml_text = XMLNS_PAT.sub('', task.Xml)  # strip the xmlns to shorten tag names
    task_xml = XML(xml_text)
    if action_eles := next((ele for ele in task_xml if ele.tag == 'Actions'), None):
        actions = [{ele.tag: ele.text for ele in action_ele} for action_ele in action_eles]
        # base_actions = as_dict['Definition']['Actions']['values']
        as_dict['Definition']['Actions']['details'] = actions
    return as_dict


def _as_dict(obj):
    as_dict = {}
    clsid = str(obj.CLSID)
    cls_enums = CLSID_ENUM_MAP.get(clsid) or {}
    for attr in obj._prop_map_get_:
        if attr not in XML_ATTRS:
            value = getattr(obj, attr)
            if isinstance(value, DispatchBaseClass):
                _value = _as_dict(value)
                try:
                    # noinspection PyTypeChecker
                    _value['values'] = [_as_dict(v) for v in value]
                except TypeError:
                    pass
                value = _value
            elif attr_enum := cls_enums.get(attr):
                value = attr_enum.get(value, value)
            as_dict[attr] = value
    return as_dict


def _walk_paths(path, hidden, recursive: bool = True):
    yield path
    for sub_path in path.GetFolders(hidden):
        if recursive:
            yield from _walk_paths(sub_path, hidden)
        else:
            yield sub_path
