#!/usr/bin/env python

from __future__ import annotations

import logging
from pathlib import Path

from cli_command_parser import Command, Counter, Option, Positional, Flag, ParamGroup, Action, main
from cli_command_parser.inputs import Path as IPath

from ds_tools.caching.decorators import cached_property
from ds_tools.argparsing.conversion.argparse_ast import Script

log = logging.getLogger(__name__)

arg_parser = 'argparse.ArgumentParser'
cli_cp_cmd = 'cli-command-parser Command'


class ParserConverter(Command, description=f'Tool to convert an {arg_parser} into a {cli_cp_cmd}'):
    action = Action()
    input: Path = Positional(type=IPath(type='file', exists=True), help=f'A file containing an {arg_parser}')
    # with ParamGroup(mutually_dependent=True, required=True):
    #     input: Path = Option('-i', type=IPath(type='file', exists=True), help=f'A file containing an {arg_parser}')
    #     # output: Path = Option('-o', type=IPath(type='file', exists=False), help='The desired output location')

    with ParamGroup('Parser Class'):
        cls_name = Option('-n', help=f"The name of an {arg_parser} subclass to process, as it appears when it's called")
        skip_ds_custom = Flag('-C', help='Skip processing the custom ArgParser subclass')

    with ParamGroup('Common'):
        verbose = Counter('-v', help='Increase logging verbosity (can specify multiple times)')
        dry_run = Flag('-D', help='Print the actions that would be taken instead of taking them')

    def _init_command_(self):
        from ds_tools.logging import init_logging

        # log_fmt = '%(asctime)s %(levelname)s %(name)s %(lineno)d %(message)s' if self.verbose > 1 else '%(message)s'
        # logging.basicConfig(level=logging.DEBUG if self.verbose else logging.INFO, format=log_fmt)
        init_logging(self.verbose, log_path=None)

    @cached_property
    def script(self) -> Script:
        extra_names = {self.cls_name} if self.cls_name else set()
        if not self.skip_ds_custom:
            extra_names |= {'ds_tools.argparsing.ArgParser', 'ds_tools.argparsing.argparser.ArgParser'}
        script = Script(self.input, extra_names)
        log.debug(f'Found {script=}')
        return script

    @action
    def pprint(self):
        for parser in self.script.parsers:
            parser.pprint()

    @action
    def dump(self):
        from ds_tools.argparsing.conversion.ast_utils import dump

        for i, parser in enumerate(self.script.parsers):
            if i:
                print('\n' + ('=' * 120) + '\n')
            print(dump(parser.init_node))

    @action
    def convert(self):
        from ds_tools.argparsing.conversion.command_builder import convert_script

        print(convert_script(self.script))


if __name__ == '__main__':
    main()
