
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

XML_TRIGGER_TYPES = {
    'TimeTrigger': 1,
    # 'CalendarTrigger': 2,  # @id = TriggerDaily
    'LogonTrigger': 9,
    'WnfStateChangeTrigger': 12,
}


CLSID_ENUM_MAP = {
    '{09941815-EA89-4B5B-89E0-2A773801FAC3}': {'Type': TRIGGER_TYPES},
    '{BAE54997-48B1-4CBE-9965-D6BE263EBEA4}': {'Type': ACTION_TYPES},
    '{9C86F320-DEE3-4DD1-B972-A303F26B061E}': {'State': TASK_STATES},
}

# DURATION_CODE_MAP = {
#     'Immediately': 'PT0M',
#     'Indefinitely': '',
#     'Do not wait': 'PT0M',
#     '15 seconds': 'PT15S',
#     '30 seconds': 'PT30S',
#     '1 minute': 'PT1M',
#     '5 minutes': 'PT5M',
#     '10 minutes': 'PT10M',
#     '15 minutes': 'PT15M',
#     '30 minutes': 'PT30M',
#     '1 hour': 'PT1H',
#     '2 hours': 'PT2H',
#     '4 hours': 'PT4H',
#     '8 hours': 'PT8H',
#     '12 hours': 'PT12H',
#     '1 day': ['P1D', 'PT24H'],
#     '3 days': ['P3D', 'PT72H'],
#     '30 days': 'P30D',
#     '90 days': 'P90D',
#     '180 days': 'P180D',
#     '365 days': 'P365D',
# }


# time portions < repetition interval are based on start time
# dow = 0-6, sunday = 0; hour = 0-23; */X = evenly divides
# {second} {minute} {hour} {day_of_month} {month} {day_of_week}
REPETITION_CODE_CRON_FORMAT_MAP = {
    'PT0M': '* * * * * *',
    'PT15S': '{second}/15 * * * * *',
    'PT30S': '{second}/30 * * * * *',
    'PT1M': '{second} * * * * *',
    'PT5M': '{second} {minute}/5 * * * *',
    'PT10M': '{second} {minute}/10 * * * *',
    'PT15M': '{second} {minute}/15 * * * *',
    'PT30M': '{second} {minute}/30 * * * *',
    'PT1H': '{second} {minute} * * * *',
    'PT2H': '{second} {minute} {hour}/2 * * *',
    'PT4H': '{second} {minute} {hour}/4 * * *',
    'PT8H': '{second} {minute} {hour}/8 * * *',
    'PT12H': '{second} {minute} {hour}/12 * * *',
    'P1D': '{second} {minute} {hour} * * *',
    'P3D': '{second} {minute} {hour} {day}/3 * *',
    'P30D': '{second} {minute} {hour} {day} * *',  # Not exact, but reduces complexity
    'P90D': '{second} {minute} {hour} {day} {month}/3 *',  # Not exact, but reduces complexity
    'P180D': '{second} {minute} {hour} {day} {month}/6 *',  # Not exact, but reduces complexity
    'P365D': '{second} {minute} {hour} {day} {month} *',  # Not exact, but reduces complexity
}
REPETITION_CODE_CRON_FORMAT_MAP['PT24H'] = REPETITION_CODE_CRON_FORMAT_MAP['P1D']
REPETITION_CODE_CRON_FORMAT_MAP['PT72H'] = REPETITION_CODE_CRON_FORMAT_MAP['P3D']


# {second} {minute} {hour} {day_of_month} {month} {day_of_week}
REPETITION_CODE_CRON_TUPLES = {
    'PT0M': ('*', '*', '*', '*', '*', '*'),
    'PT15S': (15, '*', '*', '*', '*', '*'),
    'PT30S': (30, '*', '*', '*', '*', '*'),
    'PT1M': (1, '*', '*', '*', '*', '*'),
    'PT5M': (1, 5, '*', '*', '*', '*'),
    'PT10M': (1, 10, '*', '*', '*', '*'),
    'PT15M': (1, 15, '*', '*', '*', '*'),
    'PT30M': (1, 30, '*', '*', '*', '*'),
    'PT1H': (1, 1, '*', '*', '*', '*'),
    'PT2H': (1, 1, 2, '*', '*', '*'),
    'PT4H': (1, 1, 4, '*', '*', '*'),
    'PT6H': (1, 1, 6, '*', '*', '*'),
    'PT8H': (1, 1, 8, '*', '*', '*'),
    'PT12H': (1, 1, 12, '*', '*', '*'),
    'P1D': (1, 1, 1, '*', '*', '*'),
    'P3D': (1, 1, 1, 3, '*', '*'),
    'P30D': (1, 1, 1, 1, '*', '*'),
    'P90D': (1, 1, 1, 1, 3, '*'),
    'P180D': (1, 1, 1, 1, 6, '*'),
    'P365D': (1, 1, 1, 1, 1, '*'),
}
REPETITION_CODE_CRON_TUPLES['PT24H'] = REPETITION_CODE_CRON_TUPLES['P1D']
REPETITION_CODE_CRON_TUPLES['PT72H'] = REPETITION_CODE_CRON_TUPLES['P3D']

TRIGGER_TYPE_REPETITION_CODE_MAP = {
    2: 'P1D',             # TASK_TRIGGER_DAILY
    3: 'Weekly',            # TASK_TRIGGER_WEEKLY
    4: 'Monthly',           # TASK_TRIGGER_MONTHLY
    5: 'MonthlyDayOfWeek',  # TASK_TRIGGER_MONTHLYDOW
}

# instances = {
#     'Parallel': TASK_INSTANCES_PARALLEL,
#     'Queue': TASK_INSTANCES_QUEUE,
#     'No New Instance': TASK_INSTANCES_IGNORE_NEW,
#     'Stop Existing': TASK_INSTANCES_STOP_EXISTING,
# }

RESULT_CODE_MAP = {
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

REGISTER_TASK_DEFINITION_ERROR_CODES = {
    -2147024773: 'The filename, directory name, or volume label syntax is incorrect',
    -2147024894: 'The system cannot find the file specified',
    -2147216615: 'Required element or attribute missing',
    -2147216616: 'Value incorrectly formatted or out of range',
    -2147352571: 'Access denied',
}
