
from ..com.enums import ComClassEnum
from ..com.utils import load_module

__all__ = ['taskschd', 'Actions', 'Triggers']

taskschd = load_module('taskschd.dll')


class Actions(ComClassEnum, container_cls=taskschd.IActionCollection):
    EXEC = taskschd.constants.TASK_ACTION_EXEC, taskschd.IExecAction
    COM_HANDLER = taskschd.constants.TASK_ACTION_COM_HANDLER, taskschd.IComHandlerAction
    SEND_EMAIL = taskschd.constants.TASK_ACTION_SEND_EMAIL, taskschd.IEmailAction  # deprecated
    SHOW_MESSAGE = taskschd.constants.TASK_ACTION_SHOW_MESSAGE, taskschd.IShowMessageAction  # deprecated


class Triggers(ComClassEnum, container_cls=taskschd.ITriggerCollection):
    IDLE = taskschd.constants.TASK_TRIGGER_IDLE, taskschd.IIdleTrigger
    LOGON = taskschd.constants.TASK_TRIGGER_LOGON, taskschd.ILogonTrigger
    SESSION_STATE_CHANGE = taskschd.constants.TASK_TRIGGER_SESSION_STATE_CHANGE, taskschd.ISessionStateChangeTrigger
    EVENT = taskschd.constants.TASK_TRIGGER_EVENT, taskschd.IEventTrigger
    TIME = taskschd.constants.TASK_TRIGGER_TIME, taskschd.ITimeTrigger
    DAILY = taskschd.constants.TASK_TRIGGER_DAILY, taskschd.IDailyTrigger
    WEEKLY = taskschd.constants.TASK_TRIGGER_WEEKLY, taskschd.IWeeklyTrigger
    MONTHLY = taskschd.constants.TASK_TRIGGER_MONTHLY, taskschd.IMonthlyTrigger
    MONTHLY_DOW = taskschd.constants.TASK_TRIGGER_MONTHLYDOW, taskschd.IMonthlyDOWTrigger
    BOOT = taskschd.constants.TASK_TRIGGER_BOOT, taskschd.IBootTrigger
    REGISTRATION = taskschd.constants.TASK_TRIGGER_REGISTRATION, taskschd.IRegistrationTrigger
