"""
:author: Doug Skrypa
"""

import logging
import sys
from argparse import ArgumentParser
from unittest import TestCase, main as unittest_main

from .logging import init_logging

__all__ = ['TestCaseBase', 'main']
log = logging.getLogger(__name__)


def main(description='Unit Tests', logging_kwargs=None, **kwargs):
    parser = ArgumentParser(description)
    parser.add_argument('--include', '-i', nargs='+', help='Names of test functions to include (default: all)')
    parser.add_argument('--verbose', '-v', action='count', default=0, help='Logging verbosity (can be specified multiple times to increase verbosity)')
    args, argv = parser.parse_known_args()
    logging_kwargs = logging_kwargs or {}
    logging_kwargs.setdefault('names', None)
    init_logging(args.verbose, log_path=None, **logging_kwargs)

    argv.insert(0, sys.argv[0])
    if args.include:
        test_classes = set(TestCaseBase.__subclasses__())
        for cls in TestCaseBase.__subclasses__():
            test_classes.update(cls.__subclasses__())
        names = {m: f'{cls.__name__}.{m}' for cls in test_classes for m in dir(cls)}
        for method_name in args.include:
            argv.append(names.get(method_name, method_name))

    if args.verbose:
        TestCaseBase._maybe_print = print

    kwargs.setdefault('exit', False)
    kwargs.setdefault('verbosity', 2)
    kwargs.setdefault('warnings', 'ignore')
    try:
        unittest_main(argv=argv, **kwargs)
    except KeyboardInterrupt:
        print()


class TestCaseBase(TestCase):
    _maybe_print = lambda s: None

    def setUp(self):
        self._maybe_print()

    def tearDown(self):
        self._maybe_print()
