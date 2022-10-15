#!/usr/bin/env python

from ds_tools.test_common import TestCaseBase, main
from ds_tools.core.itertools import partitioned


class ItertoolsTest(TestCaseBase):
    def test_partitioned(self):
        self.assertEqual(list(partitioned(range(0), 3)), [])
        self.assertEqual(list(partitioned(range(1), 3)), [(0,)])
        self.assertEqual(list(partitioned(range(2), 3)), [(0, 1)])
        self.assertEqual(list(partitioned(range(3), 3)), [(0, 1, 2)])
        self.assertEqual(list(partitioned(range(4), 3)), [(0, 1, 2), (3,)])
        self.assertEqual(list(partitioned(range(5), 3)), [(0, 1, 2), (3, 4)])
        self.assertEqual(list(partitioned(range(6), 3)), [(0, 1, 2), (3, 4, 5)])
        self.assertEqual(list(partitioned(range(7), 3)), [(0, 1, 2), (3, 4, 5), (6,)])
        self.assertEqual(list(partitioned(range(8), 3)), [(0, 1, 2), (3, 4, 5), (6, 7)])
        self.assertEqual(list(partitioned(range(9), 3)), [(0, 1, 2), (3, 4, 5), (6, 7, 8)])


if __name__ == '__main__':
    main()
