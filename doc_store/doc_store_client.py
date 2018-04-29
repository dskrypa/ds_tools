#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Very basic document storage DB using SQLAlchemy - REST client

Example::

    >>> client = DocStoreRestClient("localhost", 5000)
    >>> client.get_doc("test_doc_1").json()
    {'value': 200, '_id': 'test_doc_1', 'last_modified': 1525050671, '_rev': 8}
    >>> client.update_doc("test_doc_1", {"value":12345})
    <Response [200]>
    >>> client.get_doc("test_doc_1").json()
    {'value': 12345, '_id': 'test_doc_1', 'last_modified': 1525050743, '_rev': 9}

:author: Doug Skrypa
"""

import logging
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ds_tools.http import GenericRestClient
from ds_tools.utils import cached_property

log = logging.getLogger("doc_store.client")


class DocStoreRestClient(GenericRestClient):
    def __init__(self, host, port):
        super().__init__(host)
        self.port = port

    @cached_property
    def _url_fmt(self):
        """The format string to be used by this REST client object for URLs"""
        return "http://{{}}:{}/{{}}".format(self.port)

    def get_doc(self, doc_id, rev=None):
        return self.get("doc/{}".format(doc_id), params={"rev": rev})

    def update_doc(self, doc_id, content):
        return self.post("doc/{}".format(doc_id), json=content)
