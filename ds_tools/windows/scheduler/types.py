
import pythoncom
import pywintypes
import win32com
from win32com.client import gencache, Dispatch
from win32com.client.makepy import GenerateFromTypeLibSpec
from win32comext.taskscheduler import taskscheduler

from .exceptions import ComClassCreationException

try:
    taskschd = gencache.GetModuleForTypelib('{E34CB9F1-C7F7-424C-BE29-027DCC09363A}', 0, 1, 0)
except ModuleNotFoundError:
    GenerateFromTypeLibSpec('taskschd.dll', None, verboseLevel=0, bForDemand=0, bBuildHidden=1)
    taskschd = gencache.GetModuleForTypelib('{E34CB9F1-C7F7-424C-BE29-027DCC09363A}', 0, 1, 0)

__all__ = ['taskschd', 'ACTIONS', 'TRIGGERS', 'create_action', 'create_trigger']

ACTIONS = {
    taskschd.constants.TASK_ACTION_EXEC: taskschd.IExecAction,
    taskschd.constants.TASK_ACTION_COM_HANDLER: taskschd.IComHandlerAction,
    taskschd.constants.TASK_ACTION_SEND_EMAIL: taskschd.IEmailAction,  # deprecated
    taskschd.constants.TASK_ACTION_SHOW_MESSAGE: taskschd.IShowMessageAction,  # deprecated
}

TRIGGERS = {
    taskschd.constants.TASK_TRIGGER_IDLE: taskschd.IIdleTrigger,
    taskschd.constants.TASK_TRIGGER_LOGON: taskschd.ILogonTrigger,
    taskschd.constants.TASK_TRIGGER_SESSION_STATE_CHANGE: taskschd.ISessionStateChangeTrigger,
    taskschd.constants.TASK_TRIGGER_EVENT: taskschd.IEventTrigger,
    taskschd.constants.TASK_TRIGGER_TIME: taskschd.ITimeTrigger,
    taskschd.constants.TASK_TRIGGER_DAILY: taskschd.IDailyTrigger,
    taskschd.constants.TASK_TRIGGER_WEEKLY: taskschd.IWeeklyTrigger,
    taskschd.constants.TASK_TRIGGER_MONTHLY: taskschd.IMonthlyTrigger,
    taskschd.constants.TASK_TRIGGER_MONTHLYDOW: taskschd.IMonthlyDOWTrigger,
    taskschd.constants.TASK_TRIGGER_BOOT: taskschd.IBootTrigger,
    taskschd.constants.TASK_TRIGGER_REGISTRATION: taskschd.IRegistrationTrigger,
}


def create_action(task: taskschd.ITaskDefinition, action_type: int):
    """Create an Action. Necessary due to the default generated lib always using the base IAction class's CLSID."""
    action_cls = ACTIONS[action_type]
    ret = task.Actions._oleobj_.InvokeTypes(3, taskschd.LCID, 1, (9, 0), ((3, 1),), action_type)
    if ret is None:
        raise ComClassCreationException(f'Unable to create {action_cls} for {task=}')
    return Dispatch(ret, 'Create', str(action_cls.CLSID))


def create_trigger(task: taskschd.ITaskDefinition, trigger_type: int):
    trigger_cls = TRIGGERS[trigger_type]
    ret = task.Triggers._oleobj_.InvokeTypes(2, taskschd.LCID, 1, (9, 0), ((3, 1),), trigger_type)
    if ret is None:
        raise ComClassCreationException(f'Unable to create {trigger_cls} for {task=}')
    return Dispatch(ret, 'Create', str(trigger_cls.CLSID))
