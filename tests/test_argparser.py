#!/usr/bin/env python

from argparse import REMAINDER
from unittest.mock import patch

from ds_tools.test_common import TestCaseBase, main
from ds_tools.argparsing import ArgParser


class TestException(Exception):
    pass


def raise_test(*args, **kwargs):
    raise TestException


@patch('argparse.ArgumentParser.error', raise_test)
class ArgParserTest(TestCaseBase):
    def test_dynamic_args_basic_1(self):
        parser = get_dynamic_parser()
        parsed, dynamic = parser.parse_with_dynamic_args('query', ['find', '-v', 'a', 'x', '-D'])
        expected = {'action': 'find', 'obj_type': 'a', 'title': ['x'], 'dry_run': True, 'query': ['-D'], 'verbose': 1}
        self.assertDictEqual(expected, parsed.__dict__)
        self.assertFalse(dynamic)

    def test_dynamic_args_basic_2(self):
        parser = get_dynamic_parser()
        parsed, dynamic = parser.parse_with_dynamic_args('query', ['find', 'a', 'x', '-D'])
        expected = {'action': 'find', 'obj_type': 'a', 'title': ['x'], 'dry_run': True, 'query': ['-D'], 'verbose': 0}
        self.assertDictEqual(expected, parsed.__dict__)
        self.assertFalse(dynamic)

    def test_dynamic_args_basic_update(self):
        parser = get_dynamic_parser()
        parsed, dynamic = parser.parse_with_dynamic_args('query', ['find', '-D', '-v', 'a', 'x', '-v'])
        expected = {'action': 'find', 'obj_type': 'a', 'title': ['x'], 'dry_run': True, 'query': ['-v'], 'verbose': 2}
        self.assertDictEqual(expected, parsed.__dict__)
        self.assertFalse(dynamic)

    def test_dynamic_args(self):
        parser = get_dynamic_parser()
        query = ['--test=1', '-a', '2', '--foo', 'bar', '-D']
        parsed, dynamic = parser.parse_with_dynamic_args('query', ['find', 'a', 'x'] + query)
        expected_parsed = {
            'action': 'find', 'obj_type': 'a', 'title': ['x'], 'dry_run': True, 'verbose': 0, 'query': query
        }
        expected_dynamic = {'test': 1, 'a': 2, 'foo': 'bar'}
        self.assertDictEqual(expected_parsed, parsed.__dict__)
        self.assertDictEqual(expected_dynamic, dynamic)

    def test_exclusive_sets_accept(self):
        parser = get_exclusive_set_parser(False)
        parsed = parser.parse_args(['-o1', '-t', '2'])
        self.assertDictEqual({'one': '1', 'two': '2', 'three': 3, 'four': False, 'verbose': 0}, parsed.__dict__)

        parser = get_exclusive_set_parser(True)
        parsed = parser.parse_args(['test', '-o1', '-t', '2'])
        self.assertDictEqual(
            {'action': 'test', 'one': '1', 'two': '2', 'three': 3, 'four': False, 'verbose': 0}, parsed.__dict__
        )

        parser = get_exclusive_set_parser()
        parsed = parser.parse_args(['-T', '1', '-f'])
        self.assertDictEqual({'one': None, 'two': None, 'three': 1, 'four': True, 'verbose': 0}, parsed.__dict__)

        parser = get_exclusive_set_parser()
        parsed = parser.parse_args(['-T', '3', '-o', '1'])
        self.assertDictEqual({'one': '1', 'two': None, 'three': 3, 'four': False, 'verbose': 0}, parsed.__dict__)

    def test_exclusive_sets_reject(self):
        parser = get_exclusive_set_parser(False)
        with self.assertRaises(TestException):
            parsed = parser.parse_args(['-o1', '-T', '2'])

        parser = get_exclusive_set_parser(True)
        with self.assertRaises(TestException):
            parsed = parser.parse_args(['test', '-o1', '-T', '2', '--four'])

        parser = get_exclusive_set_parser()
        with self.assertRaises(TestException):
            parsed = parser.parse_args(['-T', '1', '-f', '-t', '1'])

        parser = get_exclusive_set_parser()
        with self.assertRaises(TestException):
            parsed = parser.parse_args(['-T', '3', '-o', '1', '--four'])


def get_dynamic_parser():
    parser = ArgParser()
    find_parser = parser.add_subparser('action', 'find')
    find_parser.add_argument('obj_type', choices=('a', 'b'))
    find_parser.add_argument('title', nargs='*', default=None)
    find_parser.add_argument('query', nargs=REMAINDER)
    parser.include_common_args('verbosity', 'dry_run')
    return parser


def get_exclusive_set_parser(subparser=False):
    parser = ArgParser()
    _parser = parser.add_subparser('action', 'test') if subparser else parser

    group_1 = _parser.add_argument_group('Group 1')
    group_1.add_argument('--one', '-o')
    group_1.add_argument('--two', '-t')
    group_2 = _parser.add_argument_group('Group 2')
    group_2.add_argument('--three', '-T', type=int, default=3)
    group_2.add_argument('--four', '-f', action='store_true')

    # group_3 = _parser.add_argument_group('Group 3')
    # group_3.add_argument('--five', '-F', required=True)  # If another group is chosen, then this will cause an issue
    # group_3.add_argument('--six', '-s', action='store_true')

    parser.add_mutually_exclusive_arg_sets(group_1, group_2)
    # parser.add_mutually_exclusive_arg_sets(group_1, group_2, group_3)

    parser.include_common_args('verbosity')
    return parser


if __name__ == '__main__':
    main()
