#!/usr/bin/env python

import logging
import os
import sys
from argparse import ArgumentParser, REMAINDER
from contextlib import contextmanager, redirect_stderr
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from argcomplete import CompletionFinder

sys.path.append(Path(__file__).parents[1].as_posix())
from ds_tools.test_common import TestCaseBase, main
from ds_tools.argparsing.argparser import ArgParser
from ds_tools.argparsing.argcompleter import ArgCompletionFinder
from ds_tools.output.constants import PRINTER_FORMATS

log = logging.getLogger(__name__)
IFS = '\u000b'


@contextmanager
def do_nothing():
    try:
        yield
    finally:
        pass


@patch('argcomplete.mute_stderr', do_nothing)
@patch('argcomplete.mute_stdout', do_nothing)
class ArgCompletionTest(TestCaseBase):
    def setUp(self):
        super().setUp()
        self.env_vars = {
            'COMP_TYPE': '63',
            '_ARC_DEBUG': '',
            '_ARGCOMPLETE': '1',
            '_ARGCOMPLETE_COMP_WORDBREAKS': ' \t\n"\'@><=;|&(:',
            '_ARGCOMPLETE_IFS': IFS,
            '_ARGCOMPLETE_SUPPRESS_SPACE': '1',
        }
        # Additional env args that argcomplete uses:
        # _ARGCOMPLETE_STDOUT_FILENAME
        # ARGCOMPLETE_USE_TEMPFILES
        os.environ.update(self.env_vars)

    def tearDown(self):
        super().tearDown()
        for key in self.env_vars:
            del os.environ[key]

    def _get_completions(self, parser, vanilla=False):
        sio = StringIO()
        with redirect_stderr(StringIO()):
            if vanilla:
                CompletionFinder()(parser, exit_method=lambda x: None, output_stream=sio)
            else:
                ArgCompletionFinder()(parser, exit_method=lambda x: None, output_stream=sio)
        return sio.getvalue().split(IFS)

    def test_vanilla_parser_with_choices_then_remainder(self):
        parser = vanilla_parser_with_choices_then_remainder()
        # with argcomplete_env('example.py one some_title --format '):
        with argcomplete_env('example.py one --format '):
            completions = self._get_completions(parser, False)

        self.assertListEqual(['json', 'yaml', 'raw'], completions)

    def test_vanilla_subparser_with_choices_then_remainder(self):
        parser = vanilla_subparser_with_choices_then_remainder()
        # with argcomplete_env('example.py b one some_title --format '):
        with argcomplete_env('example.py b one --format '):
            completions = self._get_completions(parser, False)

        self.assertListEqual(['json', 'yaml', 'raw'], completions)

    def test_minimal_vanilla_example_completions_ArgCompletionFinder(self):
        parser = subparser_problem_example_vanilla()
        with argcomplete_env('example.py b one some_title --format '):
            completions = self._get_completions(parser, False)

        self.assertListEqual(PRINTER_FORMATS, completions)

    def test_minimal_subclass_example_completions_ArgCompletionFinder(self):
        parser = subparser_problem_example_subclass()
        with argcomplete_env('example.py b one some_title --format '):
            completions = self._get_completions(parser, False)

        self.assertListEqual(PRINTER_FORMATS, completions)


def vanilla_parser_with_choices_then_remainder():
    obj_types = ('one', 'two', 'three')
    formats = ('json', 'yaml', 'raw')

    parser = ArgumentParser(description='Example')
    parser.add_argument('obj_type', choices=obj_types, help='Object type')
    # parser.add_argument('title', nargs='*', default=None, help='Object title (optional)')
    # parser.add_argument('--format', '-f', choices=formats, default='yaml', help='Output format')
    parser.add_argument('--format', '-f', choices=formats, help='Output format')
    parser.add_argument('query', nargs=REMAINDER, help=f'Additional query parameters')
    return parser


def vanilla_subparser_with_choices_then_remainder():
    obj_types = ('one', 'two', 'three')
    formats = ('json', 'yaml', 'raw')

    parser = ArgumentParser(description='Example')
    actions = parser.add_subparsers(dest='action', title='subcommands')
    b_parser = actions.add_parser('b', help='B')
    b_parser.add_argument('obj_type', choices=obj_types, help='Object type')
    # b_parser.add_argument('title', nargs='*', default=None, help='Object title (optional)')
    # b_parser.add_argument('--format', '-f', choices=formats, default='yaml', help='Output format')
    b_parser.add_argument('--format', '-f', choices=formats, help='Output format')
    b_parser.add_argument('query', nargs=REMAINDER, help=f'Additional query parameters')
    return parser


def subparser_problem_example_vanilla():
    parser = ArgumentParser(description='Example')
    actions = parser.add_subparsers(dest='action', title='subcommands')

    # a_parser = actions.add_parser('a', help='A')
    b_parser = actions.add_parser('b', help='B')
    # c_parser = actions.add_parser('c', help='C')

    # a_actions = a_parser.add_subparsers(dest='a_action', title='subcommands')
    # aa_parser = a_actions.add_parser('aa', help='AA')
    # aa_parser.add_argument('direction', choices=('to', 'from'), help='Direction')
    # aa_parser.add_argument('--path_filter', '-f', help='Path filter')
    # ab_parser = a_actions.add_parser('ab', help='AB')

    obj_types = ('one', 'two', 'three')

    b_parser.add_argument('obj_type', choices=obj_types, help='Object type')
    # b_parser.add_argument('title', nargs='*', default=None, help='Object title (optional)')
    # b_parser.add_argument('--escape', '-e', default='()', help='Things to escape')
    # b_parser.add_argument('--flag1', '-I', action='store_true', help='Enable flag 1')
    # b_parser.add_argument('--flag2', '-F', action='store_true', help='Enable flag 2')
    b_parser.add_argument('--format', '-f', choices=PRINTER_FORMATS, default='yaml', help='Output format to use')
    b_parser.add_argument('query', nargs=REMAINDER, help=f'Query')

    # c_parser.add_argument('obj_type', choices=obj_types, help='Object type')
    # c_parser.add_argument('rating', type=int, help='Rating out of 10')
    # c_parser.add_argument('title', nargs='*', default=None, help='Object title (optional)')
    # c_parser.add_argument('--escape', '-e', default='()', help='Things to escape')
    # c_parser.add_argument('--flag1', '-I', action='store_true', help='Enable flag 1')
    # c_parser.add_argument('query', nargs=REMAINDER, help=f'Query')

    # for _parser in (a_parser, b_parser, c_parser, aa_parser, ab_parser):
    #     _parser.add_argument('--server_path_root', '-r', metavar='PATH', help='Path root')
    #     _parser.add_argument('--server_url', '-u', metavar='URL', help='URL')
    #     _parser.add_argument('--username', '-n', help='Username')
    #     _parser.add_argument('--config', '-c', metavar='PATH', default='~/some/path.cfg', help='Config file path')
    #     _parser.add_argument('--library', '-L', default=None, help='Library name')
    #     _parser.add_argument('--verbose', '-v', action='count', default=0, help='Logging verbosity')
    #     _parser.add_argument('--dry_run', '-D', action='store_true', help='Dry run')
    # parser.add_argument('--verbose', '-v', action='count', default=0, help='Logging verbosity')

    return parser


def subparser_problem_example_subclass():
    parser = ArgParser(description='Example')

    with parser.add_subparser('action', 'a', help='A') as a_parser:
        aa_parser = a_parser.add_subparser('a_action', 'aa', help='AA')
        aa_parser.add_argument('direction', choices=('to', 'from'), help='Direction')
        aa_parser.add_argument('--path_filter', '-f', help='Path filter')
        ab_parser = a_parser.add_subparser('a_action', 'ab', help='AB')

    obj_types = ('one', 'two', 'three')

    with parser.add_subparser('action', 'b', help='B') as b_parser:
        b_parser.add_argument('obj_type', choices=obj_types, help='Object type')
        b_parser.add_argument('title', nargs='*', default=None, help='Object title (optional)')
        b_parser.add_argument('--escape', '-e', default='()', help='Things to escape')
        b_parser.add_argument('--flag1', '-I', action='store_true', help='Enable flag 1')
        b_parser.add_argument('--flag2', '-F', action='store_true', help='Enable flag 2')
        b_parser.add_argument('--format', '-f', choices=PRINTER_FORMATS, default='yaml', help='Output format to use')
        b_parser.add_argument('query', nargs=REMAINDER, help=f'Query')

    with parser.add_subparser('action', 'c', help='C') as c_parser:
        c_parser.add_argument('obj_type', choices=obj_types, help='Object type')
        c_parser.add_argument('rating', type=int, help='Rating out of 10')
        c_parser.add_argument('title', nargs='*', default=None, help='Object title (optional)')
        c_parser.add_argument('--escape', '-e', default='()', help='Things to escape')
        c_parser.add_argument('--flag1', '-I', action='store_true', help='Enable flag 1')
        c_parser.add_argument('query', nargs=REMAINDER, help=f'Query')

    parser.add_common_sp_arg('--server_path_root', '-r', metavar='PATH', help='Path root')
    parser.add_common_sp_arg('--server_url', '-u', metavar='URL', help='URL')
    parser.add_common_sp_arg('--username', '-n', help='Username')
    parser.add_common_sp_arg('--config', '-c', metavar='PATH', default='~/some/path.cfg', help='Config file path')
    parser.add_common_sp_arg('--library', '-L', default=None, help='Library name')

    parser.include_common_args('verbosity', 'dry_run')
    return parser


@contextmanager
def argcomplete_env(comp_line, comp_point=None):
    """
    :param str comp_line: The current cli text (e.g., ``bin/parse_test.py find tracks test_track --format ``)
    :param str|int comp_point: The current point in comp_line (seems to be len of comp_line?)
    """
    os.environ.update(COMP_LINE=comp_line, COMP_POINT=str(comp_point if comp_point is not None else len(comp_line)))
    try:
        yield
    finally:
        for key in ('COMP_LINE', 'COMP_POINT'):
            del os.environ[key]


if __name__ == '__main__':
    main()
