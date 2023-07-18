#!/usr/bin/env python

import sys
from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from rarfile import RarCannotExec

from ds_tools.fs.archives import ArchiveFile, Passwords
from ds_tools.test_common import TestCaseBase, main

DATA_DIR = Path(__file__).resolve().parent.joinpath('data', Path(__file__).stem)
REQUIRE_RAR = False


class ArchiveTestCase(TestCaseBase):
    tmp_dir = TemporaryDirectory()
    pw_path = Path(tmp_dir.name).joinpath('archive_passwords.txt')

    @classmethod
    def tearDownClass(cls):
        cls.tmp_dir.cleanup()

    def assert_extracted_content_matches(self, out_dir: str, exp_dir: str = 'test_dir'):
        out_path = Path(out_dir)
        expected = out_path.joinpath(exp_dir)
        self.assertTrue(expected.exists())

        exp_0 = expected.joinpath('test_file_0.txt')
        self.assertTrue(exp_0.exists())
        with exp_0.open('r', encoding='utf-8') as f:
            self.assertEqual(f.read(), 'test123\n')

        exp_1 = expected.joinpath('test_file_1.txt')
        self.assertTrue(exp_1.exists())
        with exp_1.open('r', encoding='utf-8') as f:
            self.assertEqual(f.read(), 'test123456\n')

        self.assertEqual(2, len(list(expected.iterdir())))
        self.assertEqual(1, len(list(out_path.iterdir())))

    def test_sample_archives_plain(self):
        with TemporaryDirectory() as pw_tmp_dir:
            pw_path = Path(pw_tmp_dir).joinpath('archive_passwords.txt')
            with patch.object(Passwords, 'path', pw_path):
                self.assertFalse(pw_path.exists())
                for path in DATA_DIR.joinpath('plain').iterdir():
                    with self.subTest(f'plain + {"".join(path.suffixes)}'), TemporaryDirectory() as tmp_dir:
                        ArchiveFile(path).extract_all(tmp_dir)
                        self.assert_extracted_content_matches(tmp_dir)

                self.assertFalse(pw_path.exists())

    def test_sample_archives_encrypted_content(self):
        with ExitStack() as stack:
            pw_tmp_dir = stack.enter_context(TemporaryDirectory())
            pw_path = Path(pw_tmp_dir).joinpath('archive_passwords.txt')
            stack.enter_context(patch.object(Passwords, 'path', pw_path))
            self.assertFalse(pw_path.exists())
            input_mock = stack.enter_context(patch('builtins.input', return_value='test'))
            get_input_mock = stack.enter_context(patch('ds_tools.fs.archives.get_input', return_value=True))
            for path in DATA_DIR.joinpath('enc_content').iterdir():
                with self.subTest(f'enc_content + {"".join(path.suffixes)}'):
                    with TemporaryDirectory() as tmp_dir:
                        try:
                            ArchiveFile(path).extract_all(tmp_dir)
                        except RarCannotExec as e:
                            if REQUIRE_RAR or path.suffix != '.rar':
                                raise
                            print(f'Unable to test {path.name}: {e}', file=sys.stderr)
                        else:
                            self.assert_extracted_content_matches(tmp_dir)
                            self.assertEqual(1, input_mock.call_count)
                            self.assertEqual(1, get_input_mock.call_count)

            self.assertTrue(pw_path.exists())

    @patch.object(Passwords, 'path', pw_path)
    def test_sample_archives_encrypted_full(self):
        for path in DATA_DIR.joinpath('enc_full').iterdir():
            with self.subTest(f'enc_full + {"".join(path.suffixes)}'), TemporaryDirectory() as tmp_dir:
                try:
                    ArchiveFile(path).extract_all(tmp_dir)
                except RarCannotExec as e:
                    if REQUIRE_RAR or path.suffix != '.rar':
                        raise
                    print(f'Unable to test {path.name}: {e}', file=sys.stderr)
                else:
                    self.assert_extracted_content_matches(tmp_dir)

    def test_no_inner_dir(self):
        path = DATA_DIR.joinpath('test_dir_files.7z')
        with TemporaryDirectory() as tmp_dir:
            ArchiveFile(path).extract_all(tmp_dir)
            self.assert_extracted_content_matches(tmp_dir, 'test_dir_files')


if __name__ == '__main__':
    main()
