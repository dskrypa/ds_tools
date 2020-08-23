
import calendar

DAY_LIST = calendar.day_name[-1:] + calendar.day_name[:-1]
DAY_NAME_NUM_MAP = {day: i for i, day in enumerate(DAY_LIST)}
MONTH_LIST = list(calendar.month_name)
MONTH_NAME_NUM_MAP = {month: i for i, month in enumerate(MONTH_LIST) if i}

XML_ATTRS = {'Xml', 'XmlText'}
TASK_STATES = {1: 'Disabled', 2: 'Queued', 3: 'Ready', 4: 'Running', 0: 'Unknown'}
ACTION_TYPES = {0: 'Exec', 5: 'COM Handler', 6: 'Send Email', 7: 'Show Message'}
TRIGGER_TYPES = {
    0: 'Event',             # TASK_TRIGGER_EVENT
    1: 'Time',              # TASK_TRIGGER_TIME
    2: 'Daily',             # TASK_TRIGGER_DAILY
    3: 'Weekly',            # TASK_TRIGGER_WEEKLY
    4: 'Monthly',           # TASK_TRIGGER_MONTHLY
    5: 'MonthlyDayOfWeek',  # TASK_TRIGGER_MONTHLYDOW
    6: 'OnIdle',            # TASK_TRIGGER_IDLE
    7: 'OnTaskCreation',    # TASK_TRIGGER_REGISTRATION
    8: 'OnBoot',            # TASK_TRIGGER_BOOT
    9: 'OnLogon',           # TASK_TRIGGER_LOGON
    11: 'OnSessionChange',  # TASK_TRIGGER_SESSION_STATE_CHANGE
    12: 'Custom',           # TASK_TRIGGER_CUSTOM_TRIGGER_01
}

CLSID_ENUM_MAP = {
    '{09941815-EA89-4B5B-89E0-2A773801FAC3}': {'Type': TRIGGER_TYPES},
    '{BAE54997-48B1-4CBE-9965-D6BE263EBEA4}': {'Type': ACTION_TYPES},
    '{9C86F320-DEE3-4DD1-B972-A303F26B061E}': {'State': TASK_STATES},
}

# instances = {
#     'Parallel': TASK_INSTANCES_PARALLEL,
#     'Queue': TASK_INSTANCES_QUEUE,
#     'No New Instance': TASK_INSTANCES_IGNORE_NEW,
#     'Stop Existing': TASK_INSTANCES_STOP_EXISTING,
# }

RUN_RESULT_CODE_MAP = {
    0x0: 'The operation completed successfully',
    0x1: 'Incorrect or unknown function called',
    0x2: 'File not found',
    0xA: 'The environment is incorrect',
    0x41300: 'Task is ready to run at its next scheduled time',
    0x41301: 'Task is currently running',
    0x41302: 'Task is disabled',
    0x41303: 'Task has not yet run',
    0x41304: 'There are no more runs scheduled for this task',
    0x41306: 'Task was terminated by the user',
    0x8004130F: 'Credentials became corrupted',
    0x8004131F: 'An instance of this task is already running',
    0x800710E0: 'The operator or administrator has refused the request',
    0x800704DD: 'The service is not available (Run only when logged in?)',
    0xC000013A: 'The application terminated as a result of CTRL+C',
    0xC06D007E: 'Unknown software exception',
}

REGISTER_TASK_ERROR_CODES = {
    0x80020005: 'Access denied',
    0x80041309: 'A task\'s trigger is not found',
    0x8004130A: 'One or more of the properties required to run this task have not been set',
    0x8004130C: 'The Task Scheduler service is not installed on this computer',
    0x8004130D: 'The task object could not be opened',
    0x8004130E: 'The object is either an invalid task object or is not a task object',
    0x8004130F: 'No account information could be found in the Task Scheduler security database for the task indicated',
    0x80041310: 'Unable to establish existence of the account specified',
    0x80041311: 'Corruption was detected in the Task Scheduler security database; the database has been reset',
    0x80041313: 'The task object version is either unsupported or invalid',
    0x80041314: 'The task has been configured with an unsupported combination of account settings and run time options',
    0x80041315: 'The Task Scheduler Service is not running',
    0x80041316: 'The task XML contains an unexpected node',
    0x80041317: 'The task XML contains an element or attribute from an unexpected namespace',
    0x80041318: 'Value incorrectly formatted or out of range',
    0x80041319: 'Required element or attribute missing',
    0x8004131A: 'The task XML is malformed',
    0x0004131C: (
        'The task is registered, but may fail to start. Batch logon privilege needs to be enabled for the task'
        'principal'
    ),
    0x8004131D: 'The task XML contains too many nodes of the same type',
    0x80070002: 'The system cannot find the file specified',
    0x8007007b: 'The filename, directory name, or volume label syntax is incorrect',
}
