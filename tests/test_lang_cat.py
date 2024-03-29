#!/usr/bin/env python

from ds_tools.unicode.languages import LangCat
from ds_tools.test_common import TestCaseBase, main


class LangCatTest(TestCaseBase):
    def test_spaces_ignored_for_categorize(self):
        with self.subTest('summary'):
            self.assertEqual(LangCat.HAN, LangCat.categorize('일 이', False))
        with self.subTest('detail'):
            self.assertEqual({LangCat.HAN}, LangCat.categorize('일 이', True))

    def test_punc_num_ignored_for_categorize(self):
        with self.subTest('summary'):
            self.assertEqual(LangCat.HAN, LangCat.categorize('일=1\n이=2', False))
        with self.subTest('detail'):
            self.assertEqual({LangCat.HAN}, LangCat.categorize('일=1\n이=2', True))

    def test_mix_detected(self):
        with self.subTest('summary'):
            self.assertEqual(LangCat.MIX, LangCat.categorize('일=one\n이=two', False))
        with self.subTest('detail'):
            self.assertEqual({LangCat.HAN, LangCat.ENG}, LangCat.categorize('일=two\n이=two', True))


if __name__ == '__main__':
    main()
