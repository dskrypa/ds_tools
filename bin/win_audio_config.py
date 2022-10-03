#!/usr/bin/env python

from __future__ import annotations

import logging

from cli_command_parser import Command, Positional, Option, Flag, Counter, ParamGroup, SubCommand, main

from ds_tools.output.constants import PRINTER_FORMATS

log = logging.getLogger(__name__)


class AudioConfig(Command, description='Manage Windows audio configuration'):
    sub_cmd = SubCommand()
    verbose = Counter('-v', help='Increase logging verbosity (can specify multiple times)')

    def _init_command_(self):
        from ds_tools.logging import init_logging

        init_logging(self.verbose, names=None, millis=True)


class View(AudioConfig, help='View and audio device and its properties'):
    guid = Positional(help='The guid for the device')
    format = Option('-f', choices=PRINTER_FORMATS, default='rich', help='Output format')
    extended = Flag('-x', help='Use the extended output format')

    def main(self):
        from ds_tools.output.printer import Printer
        from ds_tools.windows.registry.audio import AudioDevice

        device = AudioDevice(self.guid)
        Printer(self.format).pprint(device.serializable(not self.extended))


class List(AudioConfig, help='List audio devices and their properties'):
    format = Option('-f', choices=PRINTER_FORMATS, default='rich', help='Output format')
    active = Flag('-a', help='Filter devices to only the ones that are active')
    recursive = Flag('-r', help='Recursively populate nested keys/properties under the devices')

    def main(self):
        from ds_tools.output.printer import Printer
        from ds_tools.windows.registry.audio import AudioDevice, DeviceState

        devices = AudioDevice.find_all()
        if self.active:
            devices = [dev for dev in devices if dev.device_state == DeviceState.ACTIVE]

        data = [dev.as_dict(recursive=self.recursive) for dev in devices]
        Printer(self.format).pprint(data)


if __name__ == '__main__':
    main()
