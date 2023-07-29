"""
:author: Doug Skrypa
"""

from base64 import b64decode, b64encode, urlsafe_b64decode, urlsafe_b64encode

__all__ = ['enable_http_debug_logging']


def enable_http_debug_logging():
    import logging
    import http.client as http_client
    http_client.HTTPConnection.debuglevel = 1
    req_logger = logging.getLogger('requests.packages.urllib3')
    req_logger.setLevel(logging.DEBUG)
    req_logger.propagate = True


def b64_decode(data: str, url_safe: bool = False) -> str:
    if need_padding := len(data) % 8:
        data += '=' * (8 - need_padding)

    decode = urlsafe_b64decode if url_safe else b64decode
    return decode(data.encode('utf-8')).decode('utf-8')


def b64_encode_min(data: str, url_safe: bool = False) -> str:
    encode = urlsafe_b64encode if url_safe else b64encode
    return encode(data.encode('utf-8')).decode('utf-8').rstrip('=')
