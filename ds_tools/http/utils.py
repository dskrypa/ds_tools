"""
:author: Doug Skrypa
"""

import logging
import http.client as http_client

__all__ = ['enable_http_debug_logging']
log = logging.getLogger(__name__)


def enable_http_debug_logging():
    http_client.HTTPConnection.debuglevel = 1
    req_logger = logging.getLogger('requests.packages.urllib3')
    req_logger.setLevel(logging.DEBUG)
    req_logger.propagate = True
