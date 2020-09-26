#!/usr/bin/env python

import sys
from pathlib import Path

sys.path.append(Path(__file__).parents[1].as_posix())
from ds_tools.test_common import TestCaseBase, main
from ds_tools.core.itertools import ipartitioned


class ItertoolsTest(TestCaseBase):
    def test_ipartitioned(self):
        self.assertEqual(list(ipartitioned(range(6), 3)), [[0, 1, 2], [3, 4, 5]])
        self.assertEqual(list(ipartitioned(range(7), 3)), [[0, 1, 2], [3, 4, 5], [6]])
        self.assertEqual(list(ipartitioned(range(8), 3)), [[0, 1, 2], [3, 4, 5], [6, 7]])
        self.assertEqual(list(ipartitioned(range(9), 3)), [[0, 1, 2], [3, 4, 5], [6, 7, 8]])


if __name__ == '__main__':
    main()
