#!/usr/bin/env python

import logging
import sys
from pathlib import Path

sys.path.append(Path(__file__).parents[1].as_posix())
from ds_tools.unicode.languages import romanized_permutations
from ds_tools.test_common import TestCaseBase, main

log = logging.getLogger(__name__)


class RomanizeTest(TestCaseBase):
    def test_romanize_snsd(self):
        with self.subTest(with_space=False):
            expected = {'shoujojidai', 'syoujozidai', 'shoujojidai'}
            self.assertSetEqual(expected, set(romanized_permutations('少女時代')))

        with self.subTest(with_space=True):
            expected = {'shoujo jidai', 'syoujo zidai', 'shoujo jidai'}
            self.assertSetEqual(expected, set(romanized_permutations('少女時代', True)))


if __name__ == '__main__':
    main()
