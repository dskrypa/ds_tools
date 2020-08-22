#!/usr/bin/env python

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, PROJECT_ROOT.joinpath('bin').as_posix())
import _venv  # This will activate the venv, if it exists and is not already active

import logging
from typing import Optional

import xmltodict

sys.path.append(PROJECT_ROOT.as_posix())
from ds_tools.__version__ import __author_email__, __version__
from ds_tools.argparsing import ArgParser
from ds_tools.core import wrap_main
from ds_tools.logging import init_logging
from ds_tools.output import Printer
from ds_tools.windows.scheduler import Scheduler

log = logging.getLogger(__name__)


def parser():
    parser = ArgParser(description='Tool for managing Windows scheduled tasks')

    list_parser = parser.add_subparser('action', 'list', help='List all scheduled tasks')
    list_parser.add_argument('path', nargs='?', help='The location of the tasks to list')
    list_parser.add_argument('--format', '-f', choices=Printer.formats, default='pseudo-json', help='')
    list_parser.add_argument('--recursive', '-r', action='store_true', help='Recursively iterate through sub-paths')

    list_transform_opts = list_parser.add_argument_group('Transform Options').add_mutually_exclusive_group()
    list_transform_opts.add_argument('--summarize', '-s', action='store_true', help='Summarize task info')
    list_transform_opts.add_argument('--triggers', '-t', action='store_true', help='Only show tasks\' triggers')
    list_transform_opts.add_argument('--xml', '-x', action='store_true', help='Show task\'s parsed XML data instead of processing COM properties')

    parser.include_common_args('verbosity')
    return parser


@wrap_main
def main():
    args = parser().parse_args()
    init_logging(args.verbose, log_path=None)

    action = args.action
    if action == 'list':
        show_tasks(args.path or '\\', args.recursive, args.format, args.summarize, args.triggers, args.xml)
    else:
        raise ValueError(f'Unexpected {action=!r}')


def show_tasks(
    path: Optional[str] = '\\',
    recursive: bool = False,
    out_fmt: str = 'pseudo-json',
    summarize=False,
    triggers=False,
    xml=False,
):
    if triggers or xml:
        raw_tasks = Scheduler().get_tasks(path, recursive=recursive)
        tasks = {task.Name: xmltodict.parse(task.Xml)['Task'] for task in raw_tasks}
        if triggers:
            tasks = {name: xml['Triggers'] for name, xml in tasks.items()}
    else:
        tasks = Scheduler().get_tasks_dict(path, recursive=recursive, summarize=summarize)

    Printer(out_fmt).pprint(tasks)


if __name__ == '__main__':
    main()
