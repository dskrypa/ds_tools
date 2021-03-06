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
from ds_tools.core.main import wrap_main
from ds_tools.ddc import PlatformVcp, VCPError
from ds_tools.logging import init_logging
from ds_tools.output.color import colored

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

    cap_parser = parser.add_subparser('action', 'capabilities', 'Show monitor capabilities')
    cap_parser.add_argument('monitor', type=int, nargs='*', help='The index(es) of the monitor(s) to show (default: all)')
    cap_parser.add_argument('--feature', '-f', nargs='*', help='One or more features to display (default: all supported)')

    parser.include_common_args('verbosity')
    return parser


@wrap_main
def main():
    args = parser().parse_args(req_subparser_value=True)
    init_logging(args.verbose, log_path=None)

    action = args.action
    if action == 'list':
        monitors = PlatformVcp.get_monitors()
        for i, monitor in enumerate(monitors):
            print(f'{i}: {monitor}')
            if args.feature:
                current, max_val = monitor.get_feature_value(args.feature)
                supported = monitor.get_supported_values(args.feature) or '[not supported]'
                print(f'    current=0x{current:02X}, max=0x{max_val:02X}, supported={supported}')
            elif args.capabilities:
                print(f'    {monitor.capabilities}')
    elif action == 'get':
        monitor = PlatformVcp.get_monitors()[args.monitor]
        feature = monitor.get_feature(args.feature)
        current, cur_name, max_val, max_name = monitor.get_feature_value_with_names(feature)
        print(
            f'monitors[{args.monitor}]: {monitor}[{feature}]:'
            f' current={maybe_named(current, cur_name)}'
            f', max={maybe_named(max_val, max_name)}'
        )
    elif action == 'set':
        monitor = PlatformVcp.get_monitors()[args.monitor]
        feature = monitor.get_feature(args.feature)
        monitor[feature] = value = monitor.normalize_feature_value(feature, args.value)
        print(f'monitors[{args.monitor}][{feature}] = 0x{value:02X}')
    elif action == 'capabilities':
        monitors = PlatformVcp.get_monitors()
        included = 0
        for i, monitor in enumerate(monitors):
            if not args.monitor or i in args.monitor:
                allow_features = {monitor.get_feature(f) for f in args.feature} if args.feature else None
                if included:
                    print()
                included += 1
                print(f'Monitor {i}: {monitor}')
                log.debug(f'    Raw: {monitor.capabilities}')
                for feature, values in sorted(monitor.supported_vcp_values.items()):
                    if allow_features and feature not in allow_features:
                        continue
                    try:
                        current, max_val = monitor[feature]
                    except VCPError as e:
                        pass
                    else:
                        if feature.hide_extras:
                            values = {current}
                        else:
                            if current not in values:
                                values.add(current)

                        print(f'    {feature}:')
                        for value in sorted(values):
                            line = f'        0x{value:02X} ({feature.name_for(value, "UNKNOWN")})'
                            print(colored(line, 14) if value == current else line)
    else:
        raise ValueError(f'Unknown {action=!r}')


def maybe_named(code: int, name):
    return f'0x{code:02X} ({name})' if name else f'0x{code:02X}'


if __name__ == '__main__':
    main()
