#!/usr/bin/env python

import sys

from cli_command_parser import Command, SubCommand, Positional, Option, Flag, Counter, main

from ds_tools.__version__ import __author_email__, __version__  # noqa
from ds_tools.input import parse_bytes
from ds_tools.utils.f3 import GB_BYTES, DEFAULT_CHUNK_SIZE, F3Mode, F3Data


class F3(Command, description='Alternate F3 write/read test, based on f3write: https://github.com/AltraMayor/f3'):
    action = SubCommand()
    chunk_size = Option('-c', default=DEFAULT_CHUNK_SIZE, metavar='BYTES', type=parse_bytes, help='Chunk size to use')
    verbose = Counter('-v', help='Increase logging verbosity (can specify multiple times)')

    def _init_command_(self):
        from ds_tools.logging import init_logging

        init_logging(self.verbose, log_path=None)


class Write(F3, help='Equivalent of f3write, with more options'):
    path = Positional(help='The directory in which files should be written')
    start = Option('-s', default=1, type=int, help='The number for the first file to be written')
    end = Option('-e', type=int, help='The number for the last file to be written (default: fill disk)')
    size = Option('-S', default=GB_BYTES, metavar='BYTES', type=parse_bytes, help='File size to use (this is for testing purposes only)')
    mode = Option('-m', default='iter', choices=[e.value for e in F3Mode], help='Buffer population mode')
    rewrite = Flag('-r', help='If a file already exists for a given number, rewrite it (default: skip unless size is incorrect)')
    buffering = Option('-b', default=-1, type=int, choices=(-1, 0, 1), help='Whether to enable buffering or not')

    def main(self):
        f3data = F3Data(self.mode, self.size, self.chunk_size, self.buffering)
        if not f3data.write_files(self.path, self.start, self.end, self.rewrite):
            sys.exit(1)


class Read(F3, help='Simplified version of f3read'):
    path = Positional(help='The directory from which files should be read')

    def main(self):
        if not F3Data('iter', GB_BYTES, self.chunk_size).verify_files(self.path, self.chunk_size):
            sys.exit(1)


if __name__ == '__main__':
    main()
