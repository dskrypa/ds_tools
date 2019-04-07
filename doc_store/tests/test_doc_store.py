#!/usr/bin/env python3

import os
import sys
from unittest import TestCase, main

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from doc_store_db import DocumentDB


class DocStoreDBTester(TestCase):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.db = DocumentDB()

    def test_first_rev_is_1(self):
        doc_id = 'test_first_rev_is_1'
        self.db.update(doc_id, None)
        doc = self.db.get(doc_id)
        self.assertEqual(doc['_rev'], 1)

    def test_rev_incr(self):
        doc_id = 'test_rev_incr'
        self.db.update(doc_id, None)
        self.db.update(doc_id, None)
        doc = self.db.get(doc_id)
        self.assertEqual(doc['_rev'], 2)

    def test_prior_rev_vals(self):
        doc_id = 'test_prior_rev_vals'
        vals = [{'val': i} for i in range(3)]
        for val in vals:
            self.db.update(doc_id, val)

        for i, val in enumerate(vals):
            doc = self.db.get(doc_id, rev=i+1)
            self.assertEqual(doc['val'], val['val'])


if __name__ == '__main__':
    main(verbosity=2)
