
from ..com.enums import ComClassEnum
from ..com.utils import load_module

__all__ = ['taskschd', 'Actions', 'Triggers']

taskschd = load_module('taskschd.dll')
constants = taskschd.constants


class Actions(ComClassEnum, parent=taskschd.IActionCollection, attr='Type'):
    EXEC = constants.TASK_ACTION_EXEC, taskschd.IExecAction  # 0
    COM_HANDLER = constants.TASK_ACTION_COM_HANDLER, taskschd.IComHandlerAction  # 5
    SEND_EMAIL = constants.TASK_ACTION_SEND_EMAIL, taskschd.IEmailAction  # 6; deprecated
    SHOW_MESSAGE = constants.TASK_ACTION_SHOW_MESSAGE, taskschd.IShowMessageAction  # 7; deprecated


class Triggers(ComClassEnum, parent=taskschd.ITriggerCollection, attr='Type'):
    EVENT = constants.TASK_TRIGGER_EVENT, taskschd.IEventTrigger  # 0
    TIME = constants.TASK_TRIGGER_TIME, taskschd.ITimeTrigger  # 1
    DAILY = constants.TASK_TRIGGER_DAILY, taskschd.IDailyTrigger  # 2
    WEEKLY = constants.TASK_TRIGGER_WEEKLY, taskschd.IWeeklyTrigger  # 3
    MONTHLY = constants.TASK_TRIGGER_MONTHLY, taskschd.IMonthlyTrigger  # 4
    MONTHLY_DOW = constants.TASK_TRIGGER_MONTHLYDOW, taskschd.IMonthlyDOWTrigger  # 5
    IDLE = constants.TASK_TRIGGER_IDLE, taskschd.IIdleTrigger  # 6
    REGISTRATION = constants.TASK_TRIGGER_REGISTRATION, taskschd.IRegistrationTrigger  # 7
    BOOT = constants.TASK_TRIGGER_BOOT, taskschd.IBootTrigger  # 8
    LOGON = constants.TASK_TRIGGER_LOGON, taskschd.ILogonTrigger  # 9
    SESSION_STATE_CHANGE = constants.TASK_TRIGGER_SESSION_STATE_CHANGE, taskschd.ISessionStateChangeTrigger  # 11
