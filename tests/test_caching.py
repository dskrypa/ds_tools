#!/usr/bin/env python

import logging
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.append(Path(__file__).parents[1].as_posix())
from ds_tools.caching import TTLDBCache
from ds_tools.logging import init_logging

log = logging.getLogger(__name__)


class TTLDBCacheTest(unittest.TestCase):
    def test_entry_expiry(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db = TTLDBCache('test', cache_dir=tmp_dir, ttl=100)
            db['a'] = 'test a'
            db['b'] = 'test b'
            with db.db_session as session:
                # noinspection PyArgumentList
                entry = db._entry_cls(key='c', value='test c', created=int(time.time() - 50))
                session.merge(entry)
                entry = db._entry_cls(key='d', value='test d', created=int(time.time() - 200))
                session.merge(entry)
                session.commit()

            self.assertEqual(len(db), 3)
            self.assertIn('a', db)
            self.assertIn('b', db)
            self.assertIn('c', db)
            self.assertNotIn('d', db)

            db.expire(int(time.time() - 49))
            self.assertEqual(len(db), 2)
            self.assertIn('a', db)
            self.assertIn('b', db)
            self.assertNotIn('c', db)
            self.assertNotIn('d', db)


if __name__ == '__main__':
    init_logging(0, log_path=None)
    try:
        unittest.main(warnings='ignore', verbosity=2, exit=False)
    except KeyboardInterrupt:
        print()
