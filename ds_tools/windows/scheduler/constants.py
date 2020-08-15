
XML_ATTRS = {'Xml', 'XmlText'}

TASK_STATES = {1: 'Disabled', 2: 'Queued', 3: 'Ready', 4: 'Running', 0: 'Unknown'}

ACTION_TYPES = {0: 'Exec', 5: 'COM Handler', 6: 'Send Email', 7: 'Show Message'}
TRIGGER_TYPES = {
    0: 'Event',
    1: 'Time',
    2: 'Daily',
    3: 'Weekly',
    4: 'Monthly',
    5: 'Monthlydow',
    6: 'Idle',
    7: 'Registration',
    8: 'Boot',
    9: 'Logon',
    11: 'Session_State_Change',
    12: 'Custom',
}

CLSID_ENUM_MAP = {
    '{09941815-EA89-4B5B-89E0-2A773801FAC3}': {'Type': TRIGGER_TYPES},
    '{BAE54997-48B1-4CBE-9965-D6BE263EBEA4}': {'Type': ACTION_TYPES},
    '{9C86F320-DEE3-4DD1-B972-A303F26B061E}': {'State': TASK_STATES},
}
