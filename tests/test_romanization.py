#!/usr/bin/env python

from ds_tools.unicode.hangul import hangul_romanized_permutations_pattern, matches_hangul_permutation
from ds_tools.unicode.languages import romanized_permutations
from ds_tools.test_common import TestCaseBase, main


class RomanizeTest(TestCaseBase):
    def test_i_am_the_best(self):
        rom = 'naega jeil jal laga'
        pat = hangul_romanized_permutations_pattern('내가 제일 잘 나가')
        self.assertRegex(''.join(rom.split()), pat)

    def test_romanize_snsd(self):
        with self.subTest(with_space=False):
            expected = {'shoujojidai', 'syoujozidai', 'shoujojidai'}
            self.assertSetEqual(expected, set(romanized_permutations('少女時代')))

        with self.subTest(with_space=True):
            expected = {'shoujo jidai', 'syoujo zidai', 'shoujo jidai'}
            self.assertSetEqual(expected, set(romanized_permutations('少女時代', True)))

    def test_han_rom_pat_1(self):
        pat = hangul_romanized_permutations_pattern('우')
        for rom in ('woo', 'oo', 'wu', 'u'):
            with self.subTest(romanization=rom):
                self.assertRegex(rom, pat)

    def test_han_rom_match_1(self):
        ko = '내겐 너무 사랑스러운 그녀'
        rom = 'Naegen Neomu Sarangseureoun Geunyeo'  # OST Part 1
        self.assertTrue(matches_hangul_permutation(rom, ko))
        for k, r in zip(ko.split(), rom.split()):
            with self.subTest(han=k, rom=r):
                self.assertTrue(matches_hangul_permutation(r, k))

    def test_rom_pat_from_mix(self):
        rom = 'Naegen Neomu Sarangseureoun Geunyeo OST Part 1'
        pat = hangul_romanized_permutations_pattern('내겐 너무 사랑스러운 그녀 OST Part 1')
        self.assertRegex(''.join(rom.split()), pat)


if __name__ == '__main__':
    main()
