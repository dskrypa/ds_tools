#!/usr/bin/env python

import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

sys.path.append(Path(__file__).parents[1].as_posix())
from ds_tools.fs.archives import ArchiveFile, Passwords
from ds_tools.test_common import TestCaseBase, main

DATA_DIR = Path(__file__).resolve().parent.joinpath('data', Path(__file__).stem)


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

    @patch.object(Passwords, 'path', pw_path)
    def test_sample_archives(self):
        self.assertFalse(self.pw_path.exists())

        for path in DATA_DIR.joinpath('plain').iterdir():
            with self.subTest(f'plain + {"".join(path.suffixes)}'), TemporaryDirectory() as tmp_dir:
                ArchiveFile(path).extract_all(tmp_dir)
                self.assert_extracted_content_matches(tmp_dir)

        self.assertFalse(self.pw_path.exists())

        with patch('builtins.input', return_value='test') as input_mock:
            with patch('ds_tools.fs.archives.get_input', return_value=True) as get_input_mock:
                for path in DATA_DIR.joinpath('enc_content').iterdir():
                    with self.subTest(f'enc_content + {"".join(path.suffixes)}'), TemporaryDirectory() as tmp_dir:
                        ArchiveFile(path).extract_all(tmp_dir)
                        self.assert_extracted_content_matches(tmp_dir)
                        self.assertEqual(1, input_mock.call_count)
                        self.assertEqual(1, get_input_mock.call_count)

        self.assertTrue(self.pw_path.exists())

        for path in DATA_DIR.joinpath('enc_full').iterdir():
            with self.subTest(f'enc_full + {"".join(path.suffixes)}'), TemporaryDirectory() as tmp_dir:
                ArchiveFile(path).extract_all(tmp_dir)
                self.assert_extracted_content_matches(tmp_dir)

    def test_no_inner_dir(self):
        path = DATA_DIR.joinpath('test_dir_files.7z')
        with TemporaryDirectory() as tmp_dir:
            ArchiveFile(path).extract_all(tmp_dir)
            self.assert_extracted_content_matches(tmp_dir, 'test_dir_files')


if __name__ == '__main__':
    main()
