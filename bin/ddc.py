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
from ds_tools.windows.vcp import WindowsVCP

log = logging.getLogger(__name__)
VCP_FEATURES = {
    'input': 0x60,
}


def parser():
    parser = ArgParser(description='Utility to control monitors via DDC.  Only Windows is currently supported.')

    list_parser = parser.add_subparser('action', 'list', 'List monitors')
    list_opts = list_parser.add_mutually_exclusive_group()
    list_opts.add_argument('--capabilities', '-c', action='store_true', help='Show capabilities')
    list_opts.add_argument('--feature', '-f', choices=VCP_FEATURES.keys(), help='Show the value for the given feature for each monitor')

    set_parser = parser.add_subparser('action', 'set', 'Set a VCP feature')
    set_parser.add_argument('monitor', type=int, help='The index of the monitor on which the feature should be set')
    set_parser.add_argument('feature', choices=VCP_FEATURES.keys(), help='The feature to set')
    set_parser.add_argument('value', help='The hex value to use')

    parser.include_common_args('verbosity')
    return parser


@wrap_main
def main():
    args = parser().parse_args(req_subparser_value=True)
    init_logging(args.verbose, log_path=None)

    action = args.action
    if action == 'list':
        feature = VCP_FEATURES.get(args.feature)
        monitors = WindowsVCP.get_monitors()
        for i, monitor in enumerate(monitors):
            print(f'{i}: {monitor}')
            if feature:
                current, max_val = monitor.get_vcp_feature(feature)
                print(f'    current=0x{current:X}, max=0x{max_val:X}')
            elif args.capabilities:
                print(f'    {monitor.capabilities}')
    elif action == 'set':
        monitor = WindowsVCP.get_monitors()[args.monitor]
        feature = VCP_FEATURES[args.feature]
        value = int(args.value, 16)
        with monitor:
            result = monitor.set_vcp_feature(feature, value)
        print(f'monitors[{args.monitor}][{args.feature}] = 0x{value:x}')
        print(f'    => {result}')
    else:
        raise ValueError(f'Unknown {action=!r}')


if __name__ == '__main__':
    main()
