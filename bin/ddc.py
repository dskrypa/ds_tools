#!/usr/bin/env python

from cli_command_parser import Command, SubCommand, ParamGroup, Positional, Option, Flag, Counter, PassThru, main

from ds_tools.__version__ import __author_email__, __version__  # noqa
from ds_tools.ddc import PlatformVcp


class DDC(Command, description='Utility to control monitors via DDC.'):
    action = SubCommand()
    verbose = Counter('-v', help='Increase logging verbosity (can specify multiple times)')

    def _init_command_(self):
        from ds_tools.logging import init_logging

        init_logging(self.verbose, log_path=None)


class List(DDC, help='List monitors'):
    with ParamGroup(mutually_exclusive=True):
        capabilities = Flag('-c', help='Show capabilities')
        feature = Option('-f', help='Show the value for the given feature for each monitor')

    def main(self):
        for i, monitor in enumerate(PlatformVcp.get_monitors()):
            print(f'{i}: {monitor}')
            if self.feature:
                current, max_val = monitor.get_feature_value(self.feature)
                supported = monitor.get_supported_values(self.feature) or '[not supported]'
                print(f'    current=0x{current:02X}, max=0x{max_val:02X}, supported={supported}')
            elif self.capabilities:
                print(f'    {monitor.capabilities}')


class Get(DDC, help='Get a VCP feature value'):
    monitor = Positional(help='The ID/index of the monitor for which the feature should be retrieved')
    feature = Positional(help='The feature to get')

    def main(self):
        monitor = PlatformVcp.get_monitor(self.monitor)
        feature = monitor.get_feature(self.feature)
        current, cur_name, max_val, max_name = monitor.get_feature_value_with_names(feature)
        print(
            f'monitors[{self.monitor}]: {monitor}[{feature}]:'
            f' current={maybe_named(current, cur_name)}'
            f', max={maybe_named(max_val, max_name)}'
        )


class Set(DDC, help='Set a VCP feature'):
    monitor = Positional(
        help='The ID/index of the monitor on which the feature should be set, or ALL to set it for all monitors'
    )
    feature = Positional(help='The feature to set')
    value = Positional(help='The hex value to use')

    def main(self):
        if not (monitors := PlatformVcp.get_monitors(self.monitor)):
            print(f'No monitors found for {self.monitor=}')
        for monitor in monitors:
            feature = monitor.get_feature(self.feature)
            monitor[feature] = value = monitor.normalize_feature_value(feature, self.value)
            print(f'monitors[{monitor.n}][{feature}] = 0x{value:02X}')


class Capabilities(DDC, help='Show monitor capabilities'):
    monitor = Positional(nargs='*', help='The ID/index(es) of the monitor(s) to show (default: all)')
    feature = Option('-f', nargs='*', help='One or more features to display (default: all supported)')

    def main(self):
        for i, monitor in enumerate(PlatformVcp.get_monitors(*self.monitor)):
            if i:
                print()
            monitor.print_capabilities(self.feature)


class TurnOff(DDC, help='Turn off the specified monitors'):
    monitor = Positional(nargs='*', help='The ID pattern(s) / index(es) of the monitor(s) to show (default: all)')

    def main(self):
        for monitor in PlatformVcp.get_monitors(*self.monitor):
            feature = monitor.get_feature(0xD6)
            monitor[feature] = value = 0x4
            print(f'monitors[{monitor.n}][{feature}] = 0x{value:02X}')


def maybe_named(code: int, name):
    return f'0x{code:02X} ({name})' if name else f'0x{code:02X}'


if __name__ == '__main__':
    main()
