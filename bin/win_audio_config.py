#!/usr/bin/env python

from __future__ import annotations

import logging

from cli_command_parser import Command, Positional, Option, Flag, Counter, ParamGroup, SubCommand, main

from ds_tools.output.constants import PRINTER_FORMATS
from ds_tools.windows.registry.audio import MMDevice, DataFlow, DeviceState

log = logging.getLogger(__name__)


class AudioConfig(Command, description='Manage Windows audio configuration'):
    sub_cmd = SubCommand()
    verbose = Counter('-v', help='Increase logging verbosity (can specify multiple times)')

    def _init_command_(self):
        from ds_tools.logging import init_logging

        init_logging(self.verbose, names=None, millis=True)


class View(AudioConfig, help='View and audio device and its properties'):
    guid = Positional(help='The guid for the device')
    flow = Option('-F', type=DataFlow, default=DataFlow.RENDER, help='Data flow direction/type')
    format = Option('-f', choices=PRINTER_FORMATS, default='rich', help='Output format')
    extended = Flag('-x', help='Use the extended output format')

    def main(self):
        from ds_tools.output.printer import Printer

        device = MMDevice(self.flow, self.guid)
        Printer(self.format).pprint(device.serializable(not self.extended))


class List(AudioConfig, help='List audio devices and their properties'):
    flow = Option('-F', type=DataFlow, default=DataFlow.RENDER, help='Data flow direction/type')
    format = Option('-f', choices=PRINTER_FORMATS, default='rich', help='Output format')
    all = Flag('-a', help='Show all devices (default: only those that are present)')
    recursive = Flag('-r', help='Recursively populate nested keys/properties under the devices')

    def main(self):
        from ds_tools.output.printer import Printer

        devices = MMDevice.find_all(self.flow)
        if not self.all:
            devices = [dev for dev in devices if dev.device_state in (DeviceState.ACTIVE, DeviceState.DISABLED)]

        data = [dev.as_dict(recursive=self.recursive) for dev in devices]
        Printer(self.format).pprint(data)


class ListTypes(AudioConfig, help='List types registered in the registry'):
    format = Option('-f', choices=PRINTER_FORMATS, default='rich', help='Output format')
    recursive = Flag('-r', help='Recursively populate nested keys/properties under the devices')
    limit: int = Option('-L', help='Limit the number of results to the specified count')

    def main(self):
        from ds_tools.output.printer import Printer
        from ds_tools.windows.registry.type_lib import TypeLib

        types = TypeLib.find_all()
        if self.limit:
            types = types[:self.limit]

        data = [t.as_dict(recursive=self.recursive) for t in types]
        Printer(self.format).pprint(data)


if __name__ == '__main__':
    main()
