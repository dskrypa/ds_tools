#!/usr/bin/env python

import logging
import sys
from pathlib import Path
from unittest import main, TestCase

sys.path.append(Path(__file__).parents[1].as_posix())
from ds_tools.utils.misc import IntervalCoverage

log = logging.getLogger(__name__)


class IntervalCoverageTestCase(TestCase):
    def test_non_overlapping(self):
        arr = IntervalCoverage(8, intervals=[(1, 3), (3, 6)])
        self.assertEqual(arr.filled(), 5)
        self.assertIn((1, 3), arr)
        self.assertIn((1, 2), arr)
        self.assertIn((1, 4), arr)
        self.assertIn((1, 5), arr)
        self.assertIn((1, 6), arr)
        self.assertIn((5, 6), arr)
        self.assertIn((4, 6), arr)
        self.assertIn((3, 6), arr)
        self.assertIn((2, 6), arr)
        # arr.pprint()
        self.assertEqual(arr.min, 1)
        self.assertEqual(arr.max, 5)
        self.assertFalse(arr[arr.max + 1])

    def test_overlapping(self):
        arr = IntervalCoverage(8, intervals=[(10, 14), (4, 18), (19, 20), (19, 20), (13, 20)])
        self.assertEqual(arr.filled(), 16)
        # arr.pprint()
        self.assertEqual(arr.min, 4)
        self.assertEqual(arr.max, 19)
        self.assertFalse(arr[arr.max + 1])

    def test_high_value(self):
        arr = IntervalCoverage(64, intervals=[(1, 3), (200, (1 << 32) - 1)])
        self.assertEqual(arr.filled(), (1 << 32) - 199)
        self.assertIn((2, 3), arr)
        self.assertIn((200, 1000), arr)
        self.assertNotIn((2, 201), arr)
        self.assertNotIn((4, 201), arr)
        self.assertNotIn((4, 199), arr)
        self.assertNotIn((4, 200), arr)
        self.assertEqual(arr.min, 1)
        self.assertEqual(arr.max, (1 << 32) - 2)
        self.assertFalse(arr[arr.max + 1])


if __name__ == '__main__':
    main(exit=False, verbosity=2)
