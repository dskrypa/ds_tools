"""
Library for working with the Windows Task Scheduler

:author: Doug Skrypa
"""

import logging
from functools import cached_property
from typing import Literal

try:
    from pywintypes import com_error  # noqa
except ImportError:  # Missing optional dependency or not on Windows
    com_error = Exception

try:
    from ..com.utils import com_repr
except ImportError:  # Missing optional dependency or not on Windows
    com_repr = repr

from .exceptions import UnknownTaskError, TaskCreationException
from .utils import walk_folders, task_as_dict, norm_path, path_and_name
from .win_cron import WinCronSchedule

__all__ = ['Scheduler', 'Hidden']
log = logging.getLogger(__name__)
Hidden = bool | Literal[0, 1]


class Scheduler:
    @cached_property
    def _scheduler_instance(self):
        import pythoncom
        from win32comext.taskscheduler import taskscheduler

        # noinspection PyUnresolvedReferences
        scheduler = pythoncom.CoCreateInstance(
            taskscheduler.CLSID_CTaskScheduler, None, pythoncom.CLSCTX_INPROC_SERVER, taskscheduler.IID_ITaskScheduler
        )
        return scheduler

    @cached_property
    def _scheduler(self):
        from win32com.client import Dispatch

        service = Dispatch('Schedule.Service')
        service.Connect()
        return service

    def walk_folders(self, path: str = '\\', recursive: bool = True, hidden: Hidden = True):
        root = self._scheduler.GetFolder(path)
        yield from walk_folders(root, hidden, recursive)

    def get_tasks(self, path: str = '\\', recursive=True, hidden: Hidden = True):
        path = norm_path(path)
        tasks = []
        try:
            folder = self._scheduler.GetFolder(path)
        except com_error:
            tasks.append(self.get_task(path, hidden))
        else:
            if recursive:
                for folder in walk_folders(folder, hidden, recursive):
                    tasks.extend(folder.GetTasks(int(hidden)))
            else:
                tasks.extend(folder.GetTasks(int(hidden)))
        return tasks

    def get_task(self, path: str, hidden: Hidden = True):
        parent, name = path_and_name(path)
        try:
            folder = self._scheduler.GetFolder(parent)
        except com_error:
            raise UnknownTaskError(f'Invalid task {path=!r} - {parent=!r} does not exist')
        else:
            for task in folder.GetTasks(int(hidden)):
                if task.Name == name:
                    return task
        raise UnknownTaskError(f'Invalid task {path=!r} - {name=!r} does not exist in {parent=!r}')

    def get_tasks_dict(self, *args, summarize=False, **kwargs):
        return {task.Path: task_as_dict(task, summarize) for task in self.get_tasks(*args, **kwargs)}

    def get_task_dict(self, *args, summarize=False, **kwargs):
        return task_as_dict(self.get_task(*args, **kwargs), summarize)

    def create_exec_task(self, path: str, cmd: str, args: str, cron: str, allow_update=False):
        from ..com.utils import create_entry
        from ..libs.taskschd import taskschd

        path, name = path_and_name(path)

        sched_path = self._scheduler.GetFolder(path)
        cron = WinCronSchedule.from_cron(cron)
        task = self._scheduler.NewTask(0)

        trigger = create_entry(task.Triggers, taskschd.constants.TASK_TRIGGER_TIME)
        log.debug(f'Creating schedule with start={cron.start.isoformat()} interval={cron.interval}')
        trigger.StartBoundary = cron.start.isoformat()
        trigger.Repetition.Interval = cron.interval

        action = create_entry(task.Actions, taskschd.constants.TASK_ACTION_EXEC)
        action.Path = cmd
        if args:
            action.Arguments = args
        log.debug(f'Created action={com_repr(action)}')

        task.Settings.Enabled = True

        log.debug(f'Registering {name=} in {path=}')
        try:
            sched_path.RegisterTaskDefinition(
                name,
                task,
                taskschd.constants.TASK_CREATE_OR_UPDATE if allow_update else taskschd.constants.TASK_CREATE,
                '',
                '',
                taskschd.constants.TASK_LOGON_NONE,
            )
        except com_error as error:
            # noinspection PyTypeChecker
            raise TaskCreationException(error, path, name, cron, cmd, args)

        log.info(f'Successfully registered task={path}\\{name} with cron={cron!s} and {cmd=}')

    def _get_task_name_trigger_map(self, path: str = '\\', recursive: bool = False, hidden: Hidden = True):
        from ..com.utils import com_iter
        from ..libs.taskschd import taskschd

        return {
            task.Path: list(com_iter(task.Definition.Triggers, taskschd.LCID))
            for task in self.get_tasks(path, recursive, hidden)
        }
