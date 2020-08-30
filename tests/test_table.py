#!/usr/bin/env python

import logging
import sys
from pathlib import Path

sys.path.append(Path(__file__).parents[1].as_posix())
from ds_tools.test_common import TestCaseBase, main
from ds_tools.output.table import SimpleColumn, Table

log = logging.getLogger(__name__)


class TableTest(TestCaseBase):
    def test_mixed_types(self):
        rows = [{'a': 1.234, 'b': 1.234, 'c': 1.234}, {'a': 1.234, 'c': 1.234}, {'a': 1.234, 'b': 1.234, 'c': 1.234}]
        expected = (
            '  a    b    c\n'
            '-------------\n'
            '1.2  1.2  1.2\n'
            '1.2       1.2\n'
            '1.2  1.2  1.2\n'
        )
        table = Table(
            SimpleColumn('a', align='>', ftype='.1f'),
            SimpleColumn('b', align='>', ftype='.1f'),
            SimpleColumn('c', align='>', ftype='.1f'),
            update_width=True,
        )
        formatted = table.format_rows(rows, True)
        self.assertEqual(formatted, expected)


if __name__ == '__main__':
    main()
