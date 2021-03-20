#!/usr/bin/env python
# PYTHON_ARGCOMPLETE_OK

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, PROJECT_ROOT.joinpath('bin').as_posix())
import _venv  # This will activate the venv, if it exists and is not already active

import logging
from collections import defaultdict
from itertools import zip_longest
from typing import Optional

sys.path.append(PROJECT_ROOT.as_posix())
from ds_tools.__version__ import __author_email__, __version__
from ds_tools.argparsing import ArgParser
from ds_tools.core.main import wrap_main
from ds_tools.output import Printer, Table, TableBar

log = logging.getLogger(__name__)


def parser():
    parser = ArgParser(description='Tool for managing Windows scheduled tasks')

    with parser.add_subparser('action', 'list', help='List all scheduled tasks') as list_parser:
        list_parser.add_argument('path', nargs='?', help='The location of the tasks to list')
        list_parser.add_argument('--format', '-f', choices=Printer.formats, default='pseudo-json', help='')
        list_parser.add_argument('--recursive', '-r', action='store_true', help='Recursively iterate through sub-paths')

        list_transform_opts = list_parser.add_argument_group('Transform Options').add_mutually_exclusive_group()
        list_transform_opts.add_argument('--summarize', '-s', action='store_true', help='Summarize task info')
        list_transform_opts.add_argument('--triggers', '-t', action='store_true', help='Only show tasks\' triggers')
        list_transform_opts.add_argument('--raw_xml', '-X', action='store_true', help='Show task\'s raw XML data instead of processing COM properties')

    with parser.add_subparser('action', 'table', help='Show a table of scheduled tasks and their actions') as table_parser:
        table_parser.add_argument('path', nargs='?', help='The location of the tasks to list')
        table_parser.add_argument('--recursive', '-r', action='store_true', help='Recursively iterate through sub-paths')
        table_parser.add_argument('--times', '-t', action='store_true', help='Show the last and next run times')
        table_parser.add_argument('--hide_actions', '-A', action='store_true', help='Hide actions')
        table_parser.add_argument('--with_trigger', '-T', action='store_true', help='Only include tasks with active (enabled) triggers')

    with parser.add_subparser('action', 'create', help='Create a new task') as create_parser:
        create_parser.add_argument('path', help='The location + name for the new task')
        create_parser.add_argument('--schedule', '-s', help='Cron schedule to use', required=True)
        create_parser.add_argument('--command', '-c', help='The command to run', required=True)
        create_parser.add_argument('--args', '-a', help='Arguments to pass to the command')
        create_parser.add_argument('--update', '-u', action='store_true', help='Allow an existing scheduled task to be updated')

    parser.include_common_args('verbosity')
    return parser


@wrap_main
def main():
    args = parser().parse_args()

    from ds_tools.logging import init_logging
    init_logging(args.verbose, log_path=None)

    action = args.action
    if action == 'list':
        show_tasks(
            args.path or '\\', args.recursive, args.format, args.summarize, args.triggers, args.raw_xml
        )
    elif action == 'table':
        table_tasks(args.path or '\\', args.recursive, args.times, args.hide_actions, args.with_trigger)
    elif action == 'create':
        from ds_tools.windows.scheduler import Scheduler
        Scheduler().create_exec_task(args.path, args.command, args.args, args.schedule, allow_update=args.update)
    else:
        raise ValueError(f'Unexpected {action=!r}')


def table_tasks(
    path: Optional[str] = '\\',
    recursive: bool = False,
    times: bool = False,
    hide_actions: bool = False,
    with_trigger: bool = False,
):
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
    path: Optional[str] = '\\',
    recursive: bool = False,
    out_fmt: str = 'pseudo-json',
    summarize=False,
    triggers=False,
    raw_xml=False,
):
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
