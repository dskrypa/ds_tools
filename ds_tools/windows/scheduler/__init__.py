"""
Library for working with the Windows Task Scheduler

:author: Doug Skrypa
"""

import logging
from functools import cached_property
from typing import Optional, Literal, Union

import pythoncom
import pywintypes
from win32com.client import Dispatch
from win32comext.taskscheduler import taskscheduler

from .constants import XML_ATTRS, TASK_STATES, CLSID_ENUM_MAP
from .exceptions import UnknownTaskError
from .types import taskschd, create_action, create_trigger
from .utils import walk_paths, scheduler_obj_as_dict, task_as_dict, com_repr
from .win_cron import WinCronSchedule

__all__ = ['Scheduler', 'Hidden']
log = logging.getLogger(__name__)
Hidden = Union[bool, Literal[0, 1]]


class Scheduler:
    @cached_property
    def _scheduler_instance(self):
        # noinspection PyUnresolvedReferences
        scheduler = pythoncom.CoCreateInstance(
            taskscheduler.CLSID_CTaskScheduler, None, pythoncom.CLSCTX_INPROC_SERVER, taskscheduler.IID_ITaskScheduler
        )
        return scheduler

    @cached_property
    def _scheduler(self):
        service = Dispatch('Schedule.Service')
        service.Connect()
        return service

    def walk_paths(self, path: Optional[str] = '\\', hidden: Hidden = True, recursive: bool = True):
        hidden = int(hidden)
        root = self._scheduler.GetFolder(path)
        yield from walk_paths(root, hidden, recursive)

    def get_tasks(self, path: Optional[str] = '\\', hidden: Hidden = True, recursive=True):
        # noinspection PyUnresolvedReferences
        try:
            return self._get_tasks(path, hidden, recursive)
        except pywintypes.com_error:
            return [self.get_task(path, hidden)]

    def _get_tasks(self, path: Optional[str] = '\\', hidden: Hidden = True, recursive=True):
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

    def get_task(self, path: str, hidden: Hidden = True):
        try:
            dir_path, name = path.rsplit('\\', 1)
        except ValueError:
            dir_path = '\\'
            name = path
        tasks = self.get_tasks(dir_path, hidden, False)
        for task in tasks:
            if task.Name == name:
                return task
        raise UnknownTaskError(f'Unknown task: {path!r}')

    def get_tasks_dict(self, *args, summarize=False, **kwargs):
        tasks = self.get_tasks(*args, **kwargs)
        tasks_dict = {task.Name: task_as_dict(task) for task in tasks}
        if summarize:
            return {name: _summarize(task) for name, task in tasks_dict.items()}
        else:
            return tasks_dict

    def get_task_dict(self, *args, summarize=False, **kwargs):
        task = task_as_dict(self.get_task(*args, **kwargs))
        return _summarize(task) if summarize else task

    def create_exec_task(
        self, name: str, cmd: str, args: str, cron: str, path: Optional[str] = None, allow_update=False
    ):
        if path and '\\' in name:
            raise ValueError(f'Invalid {name=!r} given {path=!r} - name may not contain \\ when path is provided')
        elif '\\' in name:
            path, name = name.rsplit('\\', 1)
        elif not path:
            path = '\\'

        sched_path = self._scheduler.GetFolder(path)
        cron = WinCronSchedule.from_cron(cron)
        task = self._scheduler.NewTask(0)

        trigger = create_trigger(task, taskschd.constants.TASK_TRIGGER_TIME)
        log.debug(f'Creating schedule with start={cron.start.isoformat()} interval={cron.interval}')
        trigger.StartBoundary = cron.start.isoformat()
        trigger.Repetition.Interval = cron.interval

        action = create_action(task, taskschd.constants.TASK_ACTION_EXEC)
        action.Path = cmd
        if args:
            action.Arguments = args
        log.debug(f'Created action={com_repr(action)}')

        task.Settings.Enabled = True

        log.debug(f'Registering {name=} in {path=}')
        sched_path.RegisterTaskDefinition(
            name,
            task,
            taskschd.constants.TASK_CREATE_OR_UPDATE if allow_update else taskschd.constants.TASK_CREATE,
            '',
            '',
            taskschd.constants.TASK_LOGON_NONE,
        )
        log.info(f'Successfully registered task={path}\\{name} with cron={cron!s} and {cmd=}')


def _summarize(task_dict):
    definition = task_dict['Definition']
    reg_info = definition['RegistrationInfo']
    actions = definition['Actions']['values']
    return {
        'Location': task_dict['Path'],
        'Status': task_dict['State'],
        'LastRun': task_dict['LastRunTime'],
        'NextRun': task_dict['NextRunTime'],
        'LastResult': task_dict['LastTaskResult'],
        'Enabled': task_dict['Enabled'],
        'Author': reg_info['Author'],
        'Description': reg_info['Description'],
        'RunAs': definition['Principal']['UserId'],
        'Actions': actions,
        'Triggers': definition['Triggers']
        # 'Schedule': [f'{t["Type"]}: {t["cron"]}' for t in definition['Triggers']['values']],
        # 'Cron': list(filter(None, (t['cron'] for t in definition['Triggers']['values']))),
    }
