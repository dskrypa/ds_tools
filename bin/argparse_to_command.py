#!/usr/bin/env python

from __future__ import annotations

import ast
import logging
from pathlib import Path

from cli_command_parser import Command, Counter, Option, Positional, Flag, ParamGroup, SubCommand, main
from cli_command_parser.inputs import Path as IPath

from ds_tools.caching.decorators import cached_property

log = logging.getLogger(__name__)

arg_parser = 'argparse.ArgumentParser'
cli_cp_cmd = 'cli-command-parser Command'


class ParserConverter(Command, description=f'Tool to convert an {arg_parser} into a {cli_cp_cmd}'):
    action = SubCommand()
    input: Path
    # with ParamGroup(mutually_dependent=True, required=True):
    #     input: Path = Option('-i', type=IPath(type='file', exists=True), help=f'A file containing an {arg_parser}')
    #     # output: Path = Option('-o', type=IPath(type='file', exists=False), help='The desired output location')
    smart_for = Flag(
        '--no-smart-for', '-S', default=True, help='Disable "smart" for loop handling, which attempts to dedupe common subparser params'
    )
    with ParamGroup('Common'):
        verbose = Counter('-v', help='Increase logging verbosity (can specify multiple times)')
        dry_run = Flag('-D', help='Print the actions that would be taken instead of taking them')

    def _init_command_(self):
        from ds_tools.logging import init_logging

        # log_fmt = '%(asctime)s %(levelname)s %(name)s %(lineno)d %(message)s' if self.verbose > 1 else '%(message)s'
        # logging.basicConfig(level=logging.DEBUG if self.verbose else logging.INFO, format=log_fmt)
        init_logging(self.verbose, log_path=None)

    @cached_property
    def script(self):
        from ds_tools.argparsing.conversion import Script

        script = Script(self.input, self.smart_for)
        log.debug(f'Found {script=}')
        return script


class Convert(ParserConverter):
    input: Path = Positional(type=IPath(type='file', exists=True), help=f'A file containing an {arg_parser}')

    def main(self):
        from ds_tools.argparsing.conversion import convert_script

        print(convert_script(self.script))


class Pprint(ParserConverter):
    input: Path = Positional(type=IPath(type='file', exists=True), help=f'A file containing an {arg_parser}')

    def main(self):
        for parser in self.script.parsers:
            parser.pprint()


class Dump(ParserConverter):
    input: Path = Positional(type=IPath(type='file', exists=True), help=f'A file containing an {arg_parser}')
    parsed = Flag('-p', help='Dump parsed nodes (default: all raw content)')
    compact = Flag('-c', help='Print more compact output for the dump action')

    def main(self):
        from ds_tools.argparsing.conversion.ast_utils import dump

        if self.parsed:
            nodes = (node for p in self.script.parsers for node in p.walk_nodes())
        else:
            nodes = self.script.root_node.body if self.compact else [self.script.root_node]

        dump_func = ast.dump if self.compact else dump
        for node in nodes:
            print(dump_func(node))


if __name__ == '__main__':
    main()
