#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
:author: Doug Skrypa
"""

import logging
import os
from atexit import register
from contextlib import suppress
from weakref import WeakSet

import requests
from cachetools import TTLCache
# from urllib3 import disable_warnings as disable_urllib3_warnings
from wrapt import synchronized

from .exceptions import CodeBasedRestException
from .utils import cached

__all__ = ["proxy_bypass_append", "requests_session", "http_cleanup", "GenericRestClient"]
log = logging.getLogger("ds_tools.http")

# disable_urllib3_warnings()

__instances = WeakSet()


def proxy_bypass_append(host):
    """
    Adds the given host to os.environ["no_proxy"] if it was not already present.  This environment variable is used by
    the Requests library to disable proxies for requests to particular hosts.

    :param str host: A host to add to os.environ["no_proxy"]
    """
    if "no_proxy" not in os.environ:
        os.environ["no_proxy"] = host
    elif host not in os.environ["no_proxy"]:
        os.environ["no_proxy"] += "," + host


def requests_session(http_proxy=None, https_proxy=None):
    session = requests.Session()

    if http_proxy:
        session.proxies["http"] = http_proxy
    if https_proxy:
        session.proxies["https"] = https_proxy

    with synchronized(__instances):
        __instances.add(session)
    return session


class GenericRestClient:
    """
    :param str host: Hostname to communicate with
    :param str|int port: Port to use
    :param str path_prefix: URL path prefix for all requests
    :param str proto: Protocol to use (http, https, etc.)
    """
    def __init__(self, host, port=None, path_prefix=None, proto="http"):
        self.host = host
        self.port = port
        self.proto = proto
        self.path_prefix = path_prefix

    @property
    def path_prefix(self):
        return self._path_prefix

    @path_prefix.setter
    def path_prefix(self, value):
        if value:
            value = value if not value.startswith("/") else value[1:]
            self._path_prefix = value if value.endswith("/") else value + "/"
        else:
            self._path_prefix = ""

    @property
    def _url_fmt(self):
        """The format string to be used by this REST client object for URLs"""
        host_port = "{}:{}".format(self.host, self.port) if self.port else self.host
        return "{}://{}/{}{{}}".format(self.proto, host_port, self.path_prefix)

    def url_for(self, endpoint):
        return self._url_fmt.format(endpoint if not endpoint.startswith("/") else endpoint[1:])

    @synchronized
    @cached(TTLCache(1, 86400))
    def _get_session(self):
        session = requests_session()
        return session

    @property
    def session(self):
        return self._get_session()

    def request(self, method, endpoint, *, raise_non_200=True, **kwargs):
        url = self.url_for(endpoint)
        log.debug("{} -> {}".format(method, url))
        try:
            resp = self.session.request(method, url, **kwargs)
        except requests.RequestException as e:
            raise CodeBasedRestException(e, endpoint)
        if raise_non_200 and not (200 <= resp.status_code <= 299):
            raise CodeBasedRestException(resp, endpoint)
        return resp

    def get(self, endpoint, **kwargs):
        return self.request("GET", endpoint, **kwargs)

    def put(self, endpoint, **kwargs):
        return self.request("PUT", endpoint, **kwargs)

    def post(self, endpoint, **kwargs):
        return self.request("POST", endpoint, **kwargs)

    def delete(self, endpoint, **kwargs):
        return self.request("DELETE", endpoint, **kwargs)


@register
def http_cleanup():
    with synchronized(__instances):
        for session in __instances:
            with suppress(Exception):
                session.close()
