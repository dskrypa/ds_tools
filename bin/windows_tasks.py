#!/usr/bin/env python

from cli_command_parser import Command, SubCommand, ParamGroup, Positional, Option, Flag, Counter, main

from ds_tools.__version__ import __author_email__, __version__  # noqa
from ds_tools.output.constants import PRINTER_FORMATS


class TaskScheduler(Command, description='Tool for managing Windows scheduled tasks'):
    action = SubCommand()
    verbose = Counter('-v', help='Increase logging verbosity (can specify multiple times)')

    def _init_command_(self):
        from ds_tools.logging import init_logging

        init_logging(self.verbose, log_path=None)


class List(TaskScheduler, help='List all scheduled tasks'):
    path = Positional(nargs='?', help='The location of the tasks to list')
    format = Option('-f', default='pseudo-json', choices=PRINTER_FORMATS)
    recursive = Flag('-r', help='Recursively iterate through sub-paths')

    with ParamGroup('Transform', mutually_exclusive=True):
        summarize = Flag('-s', help='Summarize task info')
        triggers = Flag('-t', help="Only show tasks' triggers")
        raw_xml = Flag('-X', help="Show task's raw XML data instead of processing COM properties")

    def main(self):
        show_tasks(self.path or '\\', self.recursive, self.format, self.summarize, self.triggers, self.raw_xml)


class ShowTable(TaskScheduler, choice='table', help='Show a table of scheduled tasks and their actions'):
    path = Positional(nargs='?', help='The location of the tasks to list')
    recursive = Flag('-r', help='Recursively iterate through sub-paths')
    times = Flag('-t', help='Show the last and next run times')
    hide_actions = Flag('-A', help='Hide actions')
    with_trigger = Flag('-T', help='Only include tasks with active (enabled) triggers')

    def main(self):
        table_tasks(self.path or '\\', self.recursive, self.times, self.hide_actions, self.with_trigger)


class Create(TaskScheduler, help='Create a new task'):
    path = Positional(help='The location + name for the new task')
    schedule = Option('-s', required=True, help='Cron schedule to use')
    command = Option('-c', required=True, help='The command to run')
    args = Option('-a', help='Arguments to pass to the command')
    update = Flag('-u', help='Allow an existing scheduled task to be updated')

    def main(self):
        from ds_tools.windows.scheduler import Scheduler

        Scheduler().create_exec_task(self.path, self.command, self.args, self.schedule, allow_update=self.update)


def table_tasks(
    path: str | None = '\\',
    recursive: bool = False,
    times: bool = False,
    hide_actions: bool = False,
    with_trigger: bool = False,
):
    from collections import defaultdict
    from itertools import zip_longest
    from ds_tools.output import Table, TableBar
    from ds_tools.windows.scheduler import Scheduler

    show_actions = not hide_actions
    tasks = Scheduler().get_tasks_dict(path, recursive=recursive, summarize=True)
    rows = []
    for task in tasks.values():
        triggers = task['Triggers']
        if with_trigger and (not triggers or not any(t['Enabled'] for t in triggers)):
            continue
        actions = task['Actions']
        row = {
            'Location': task['Location'],
            # 'Run As': task['RunAs'],
            'Enabled': task['Enabled'],
            # 'Status': task['Status'],
            'Last': task['LastRun'],
            'Next': task['NextRun'],
            'Trigger': '',
            'Action': '',
        }
        if not times:
            row.pop('Last')
            row.pop('Next')
        if show_actions:
            row.pop('Action')

        i = -1
        for i, (trigger, action) in enumerate(zip_longest(triggers, actions)):
            if i:
                row = defaultdict(str)
            if trigger:
                cron = str(trigger['cron'])
                if cron.startswith('<'):
                    row['Trigger'] = cron
                else:
                    row['Trigger'] = f'{trigger["Type"]}: {cron}'
            if action and show_actions:
                if (a_type := action['Type']) == 'IExecAction':
                    row['Action'] = f'{a_type}: {action["Path"]} {action["Arguments"]}'
                else:
                    row['Action'] = f'{a_type}: {action}'
            rows.append(row)

        if i < 0:
            rows.append(row)
        rows.append(TableBar())

    Table.auto_print_rows(rows, sort_keys=False)


def show_tasks(
    path: str | None = '\\',
    recursive: bool = False,
    out_fmt: str = 'pseudo-json',
    summarize=False,
    triggers=False,
    raw_xml=False,
):
    from ds_tools.output import Printer
    from ds_tools.windows.scheduler import Scheduler

    if raw_xml:
        for task in Scheduler().get_tasks(path, recursive=recursive):
            print(task.Xml)
        return
    else:
        tasks = Scheduler().get_tasks_dict(path, recursive=recursive, summarize=summarize)
        if triggers:
            tasks = {_path: task['Definition']['Triggers'] for _path, task in tasks.items()}

    Printer(out_fmt).pprint(tasks)


if __name__ == '__main__':
    main()
