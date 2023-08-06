#!/usr/bin/env python

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, main

from ds_tools.fs.paths import PathValidator, sanitize_file_name, unique_path, path_repr


class PathTest(TestCase):
    # region unique_path

    def test_unique_path_target_available(self):
        with TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            expected = tmp_dir.joinpath('foo.bar')
            self.assertEqual(expected, unique_path(tmp_dir, 'foo', '.bar'))
            self.assertEqual(expected, unique_path.for_path(expected))

    def test_unique_path_target_exists(self):
        with TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            tmp_dir.joinpath('foo.bar').touch()
            self.assertEqual(tmp_dir.joinpath('foo-1.bar'), unique_path(tmp_dir, 'foo', '.bar'))
            self.assertEqual(tmp_dir.joinpath('foo-1.bar'), unique_path.for_path(tmp_dir.joinpath('foo.bar')))

    def test_unique_path_targets_exist(self):
        with TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            tmp_dir.joinpath('foo.bar').touch()
            tmp_dir.joinpath('foo-1.bar').touch()
            tmp_dir.joinpath('foo-2.bar').touch()
            self.assertEqual(tmp_dir.joinpath('foo-3.bar'), unique_path(tmp_dir, 'foo', '.bar'))
            self.assertEqual(tmp_dir.joinpath('foo-3.bar'), unique_path.for_path(tmp_dir.joinpath('foo.bar')))

    # endregion

    # region Path Validator

    def test_reserved_names_are_invalid(self):
        validate = PathValidator().validate
        for name in ('CON', 'PRN', 'AUX', 'CLOCK$', 'NUL', 'COM1', 'COM9', 'LPT1', 'LPT9', ':'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                validate(name)
            name = f'{name}.txt'
            with self.subTest(name=name), self.assertRaises(ValueError):
                validate(name)

    def test_invalid_chars_are_invalid(self):
        validate = PathValidator().validate
        for name in ('foo\t.txt', 'bar:.txt', 'baz\n'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                validate(name)

    def test_sanitize_file_name(self):
        self.assertEqual('foo-bar%3F.txt', sanitize_file_name('foo:bar?.txt'))
        self.assertEqual('foo_bar%3F.txt', sanitize_file_name('foo:bar?.txt', {':': '_'}))
        self.assertEqual('_AUX', sanitize_file_name('AUX'))

    # endregion

    # region path_repr

    def test_path_repr_relative(self):
        self.assertEqual('~/foo/bar/baz.txt', path_repr(Path.home().joinpath('foo/bar/baz.txt')))

    def test_path_repr_non_relative(self):
        self.assertEqual('/foo/bar/baz.txt', path_repr(Path('/foo/bar/baz.txt')))

    def test_path_repr_dir(self):
        self.assertEqual('/foo/bar/', path_repr(Path('/foo/bar'), True))
        self.assertEqual('/foo/bar', path_repr(Path('/foo/bar'), False))
        with TemporaryDirectory() as tmp:
            path = Path(tmp).joinpath('foo')
            path.mkdir()
            self.assertTrue(path_repr(path).endswith('/'))
            self.assertFalse(path_repr(path, False).endswith('/'))

    # endregion


if __name__ == '__main__':
    main(verbosity=2)
