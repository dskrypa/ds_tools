#!/usr/bin/env python

from unittest import TestCase, main

from ds_tools.output.prefix import LoggingPrefix, get_present_participle


class PresentParticipleTest(TestCase):
    def test_ends_with_e(self):
        cases = {
            'create': 'creating',
            'delete': 'deleting',
            'move': 'moving',
            'replace': 'replacing',
            'remove': 'removing',
            'rename': 'renaming',
            'save': 'saving',
            'update': 'updating',
            'levee': 'leveeing',
            'canoe': 'canoeing',
            'dye': 'dyeing',
            'imbue': 'imbuing',
            'singe': 'singeing',
            'dredge': 'dredging',
        }
        for base, expected in cases.items():
            with self.subTest(base):
                self.assertEqual(expected, get_present_participle(base))

    def test_ends_with_ic(self):
        cases = {
            'panic': 'panicking',
            'mimic': 'mimicking',
        }
        for base, expected in cases.items():
            with self.subTest(base):
                self.assertEqual(expected, get_present_participle(base))

    def test_do_double_last(self):
        cases = {
            'begin': 'beginning',
            'reset': 'resetting',
            'run': 'running',
            'bin': 'binning',
            'spin': 'spinning',
            'beg': 'begging',
            'grab': 'grabbing',
            'drop': 'dropping',
            'swim': 'swimming',
            'hop': 'hopping',
            'control': 'controlling',
        }
        for base, expected in cases.items():
            with self.subTest(base):
                self.assertEqual(expected, get_present_participle(base))

    def test_no_double_last(self):
        cases = {
            'meet': 'meeting',
            'preen': 'preening',
            'moon': 'mooning',
            'bargain': 'bargaining',
            'train': 'training',
            'stream': 'streaming',
        }
        for base, expected in cases.items():
            with self.subTest(base):
                self.assertEqual(expected, get_present_participle(base))

    def test_maybe_double_last_tricky(self):
        cases = {
            'open': 'opening',

            'pen': 'penning',

            'exit': 'exiting',
            'limit': 'limiting',

            'emit': 'emitting',
            'sit': 'sitting',
        }
        for base, expected in cases.items():
            with self.subTest(base):
                self.assertEqual(expected, get_present_participle(base))

    def test_other(self):
        cases = {
            'add': 'adding',
            'copy': 'copying',
            'send': 'sending',
        }
        for base, expected in cases.items():
            with self.subTest(base):
                self.assertEqual(expected, get_present_participle(base))

    def test_verb_phrases(self):
        cases = {
            'set up': 'setting up',
        }
        for base, expected in cases.items():
            with self.subTest(base):
                self.assertEqual(expected, get_present_participle(base))


class LoggingPrefixTest(TestCase):
    def test_dynamic_verbs(self):
        self.assertEqual('Testing', LoggingPrefix(False)['test'])
        self.assertEqual('Testing', LoggingPrefix(False).test)
        self.assertEqual('Setting up', LoggingPrefix(False).set_up)
        self.assertEqual('[DRY RUN] Would test', LoggingPrefix(True)['test'])
        self.assertEqual('[DRY RUN] Would test', LoggingPrefix(True).test)
        self.assertEqual('[DRY RUN] Would set up', LoggingPrefix(True).set_up)


if __name__ == '__main__':
    main(verbosity=2)
