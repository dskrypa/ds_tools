#!/usr/bin/env python

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, PROJECT_ROOT.joinpath('bin').as_posix())
import _venv  # This will activate the venv, if it exists and is not already active

import logging

sys.path.append(PROJECT_ROOT.joinpath('lib').as_posix())
from ds_tools.__version__ import __author_email__, __version__
from ds_tools.argparsing import ArgParser
from ds_tools.core import wrap_main
from ds_tools.logging import init_logging
from ds_tools.windows.vcp import WindowsVCP, get_feature, FEATURE_NAMES

log = logging.getLogger(__name__)


def parser():
    parser = ArgParser(description='Utility to control monitors via DDC.  Only Windows is currently supported.')

    list_parser = parser.add_subparser('action', 'list', 'List monitors')
    list_opts = list_parser.add_mutually_exclusive_group()
    list_opts.add_argument('--capabilities', '-c', action='store_true', help='Show capabilities')
    list_opts.add_argument('--feature', '-f', help='Show the value for the given feature for each monitor')

    get_parser = parser.add_subparser('action', 'get', 'Get a VCP feature value')
    get_parser.add_argument('monitor', type=int, help='The index of the monitor for which the feature should be retrieved')
    get_parser.add_argument('feature', help='The feature to get')

    set_parser = parser.add_subparser('action', 'set', 'Set a VCP feature')
    set_parser.add_argument('monitor', type=int, help='The index of the monitor on which the feature should be set')
    set_parser.add_argument('feature', help='The feature to set')
    set_parser.add_argument('value', help='The hex value to use')

    parser.include_common_args('verbosity')
    return parser


@wrap_main
def main():
    args = parser().parse_args(req_subparser_value=True)
    init_logging(args.verbose, log_path=None)

    action = args.action
    if action == 'list':
        feature = get_feature(args.feature) if args.feature else None
        monitors = WindowsVCP.get_monitors()
        for i, monitor in enumerate(monitors):
            print(f'{i}: {monitor}')
            if feature:
                current, max_val = monitor.get_vcp_feature(feature)
                supported = monitor.get_supported_values(feature) or '[not supported]'
                print(f'    current=0x{current:02X}, max=0x{max_val:02X}, supported={supported}')
            elif args.capabilities:
                print(f'    {monitor.capabilities}')
    elif action == 'get':
        monitor = WindowsVCP.get_monitors()[args.monitor]
        feature = get_feature(args.feature)
        current, cur_name, max_val, max_name = monitor.get_vcp_feature_with_names(feature)
        print(
            f'monitors[{args.monitor}]: {monitor}[{maybe_named(feature, FEATURE_NAMES.get(feature))}]:'
            f' current={maybe_named(current, cur_name)}'
            f', max={maybe_named(max_val, max_name)}'
        )
    elif action == 'set':
        monitor = WindowsVCP.get_monitors()[args.monitor]
        feature = get_feature(args.feature)
        monitor[feature] = value = monitor.normalize_feature_value(feature, args.value)
        print(f'monitors[{args.monitor}][{maybe_named(feature, FEATURE_NAMES.get(feature))}] = 0x{value:02X}')
    else:
        raise ValueError(f'Unknown {action=!r}')


def maybe_named(code: int, name):
    return f'0x{code:02X} ({name})' if name else f'0x{code:02X}'


if __name__ == '__main__':
    main()
