#!/usr/bin/env python

import logging
import sys
from pathlib import Path

sys.path.append(Path(__file__).parents[1].as_posix())
from ds_tools.logging import init_logging
from ds_tools.input.parsers import parse_bytes
from ds_tools.test_common import TestCaseBase, main

log = logging.getLogger(__name__)


class InputParserTest(TestCaseBase):
    def test_parse_bytes(self):
        cases = {
            '1 KB': 1024,
            '1KB': 1024,
            '1.5 KB': 1536,
            '1': 1,
            '1 B': 1,
            '20 MB': 20971520,
            '-20 MB': -20971520,
            200: 200,
        }
        correct = 0
        for value, expected in cases.items():
            parsed = parse_bytes(value)
            if parsed == expected:
                correct += 1
            else:
                log.warning(f'parse_bytes({value}) => {parsed=:,d}  {expected=:,d}', extra={'color': 'red'})

        log.info(f'{correct} / {len(cases)} passed')
        self.assertEqual(correct, len(cases))


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print()
