#!/usr/bin/env python

import inspect
import logging
import tempfile
import unittest
from pathlib import Path

from ds_tools.logging import init_logging


class LoggingInitTest(unittest.TestCase):
    def _cleanup_handlers(self, *names):
        for name in names:
            logger = logging.getLogger(name)
            while logger.handlers:
                logger.handlers[0].close()
                del logger.handlers[0]

    def test_log_path_name(self):
        this_file_name = get_expected_name()
        with tempfile.TemporaryDirectory() as tmp_dir:
            log_path = init_logging(filename_fmt='{prog}.log', file_dir=tmp_dir, names='test', streams=False)
            self.assertEqual(Path(log_path).name, f'{this_file_name}.log')
            self._cleanup_handlers('test')

    def test_log_path_uniq(self):
        this_file_name = get_expected_name()
        with tempfile.TemporaryDirectory() as tmp_dir:
            log_path_1 = init_logging(filename_fmt='{prog}{uniq}.log', file_dir=tmp_dir, names='test1', streams=False)
            log_path_2 = init_logging(filename_fmt='{prog}{uniq}.log', file_dir=tmp_dir, names='test2', streams=False)
            log_path_3 = init_logging(filename_fmt='{prog}{uniq}.log', file_dir=tmp_dir, names='test3', streams=False)
            self.assertEqual(Path(log_path_1).stem, this_file_name)
            self.assertEqual(Path(log_path_2).stem, f'{this_file_name}-0')
            self.assertEqual(Path(log_path_3).stem, f'{this_file_name}-1')
            self._cleanup_handlers('test1', 'test2', 'test3')


def get_expected_name():
    if __name__ != '__main__':
        try:
            return Path(inspect.getsourcefile(inspect.stack()[-1][0])).stem
        except (TypeError, AttributeError):
            pass
    return Path(__file__).stem


if __name__ == '__main__':
    try:
        unittest.main(warnings='ignore', verbosity=2, exit=False)
    except KeyboardInterrupt:
        print()
