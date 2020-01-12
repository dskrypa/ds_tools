"""
Helpers for working with Requests sessions.

:author: Doug Skrypa
"""

import logging
import os
from atexit import register as atexit_register
from contextlib import suppress
from urllib.parse import urlencode
from weakref import WeakSet

import requests
# from urllib3 import disable_warnings as disable_urllib3_warnings
from wrapt import synchronized

from ..core import rate_limited
from ..concurrency.futures import as_future
from .exceptions import CodeBasedRestException

__all__ = ['proxy_bypass_append', 'requests_session', 'http_cleanup', 'RestClient']
log = logging.getLogger(__name__)
__instances = WeakSet()

# disable_urllib3_warnings()    # Mostly needed for dealing with un-verified SSL connections

IMITATE_HEADERS = {
    'firefox@win10': {
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
        'Cache-Control': 'no-cache',
        'Pragma': 'no-cache',
        'Upgrade-Insecure-Requests': '1',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:66.0) Gecko/20100101 Firefox/66.0'
    }
}


def proxy_bypass_append(host):
    """
    Adds the given host to os.environ['no_proxy'] if it was not already present.  This environment variable is used by
    the Requests library to disable proxies for requests to particular hosts.

    :param str host: A host to add to os.environ['no_proxy']
    """
    if 'no_proxy' not in os.environ:
        os.environ['no_proxy'] = host
    elif host not in os.environ['no_proxy']:
        os.environ['no_proxy'] += ',' + host


def requests_session(http_proxy=None, https_proxy=None):
    session = requests.Session()

    if http_proxy:
        session.proxies['http'] = http_proxy
    if https_proxy:
        session.proxies['https'] = https_proxy

    with synchronized(__instances):
        __instances.add(session)
    return session


class RestClient:
    """
    :param str host: Hostname to communicate with
    :param str|int port: Port to use
    :param str prefix: URL path prefix for all requests
    :param str proto: Protocol to use (http, https, etc.) (default: http)
    :param bool verify: Argument to pass in all requests governing SSL cert verification (see:
      `requests.Session.request <http://docs.python-requests.org/en/master/api/#requests.Session.request>`_)
    :param class exc: Exception class to raise on non-2xx responses (default: :class:`CodeBasedRestException`)
    :param function session_factory: A function that accepts no arguments and returns a `requests.Session
      <http://docs.python-requests.org/en/master/api/#requests.Session>`_ object (default: :func:`requests_session`)
    :param str imitate: A browser to imitate.  Valid values are keys of :data:`IMITATE_HEADERS` (default: None)
    :param float rate_limit: A rate limit (in seconds) for all requests made by this object (default: no limit)
    """
    def __init__(
            self, host, port=None, *, prefix=None, proto='http', verify=None, exc=None, session_factory=None,
            imitate=None, rate_limit=0, log_params=False
    ):
        if imitate and (imitate not in IMITATE_HEADERS):
            err_fmt = 'Invalid imitate value ({!r}) - must be one of: {}'
            raise ValueError(err_fmt.format(imitate, ', '.join(sorted(IMITATE_HEADERS.keys()))))
        self.host = host
        self.port = port
        self.proto = proto
        self.path_prefix = prefix
        self._exc_type = exc or CodeBasedRestException
        self._verify_ssl = verify
        self._session_factory = session_factory or requests_session
        self.__session = None
        self._imitate = imitate
        self._log_params = log_params
        if rate_limit:
            self.request = rate_limited(rate_limit)(self.request)

    @property
    def port(self):
        """The port to connect to; defined as a property so subclasses may use it as such"""
        return self.__port

    @port.setter
    def port(self, value):
        self.__port = value

    @property
    def path_prefix(self):
        """A prefix for all URL paths that is used when generating the URL for a given REST endpoint"""
        return self._path_prefix

    @path_prefix.setter
    def path_prefix(self, value):
        if value:
            value = value if not value.startswith('/') else value[1:]
            self._path_prefix = value if value.endswith('/') else value + '/'
        else:
            self._path_prefix = ''

    @property
    def _url_fmt(self):
        """The format string to be used by this REST client object for URLs"""
        host_port = '{}:{}'.format(self.host, self.port) if self.port else self.host
        return '{}://{}/{}{{}}'.format(self.proto, host_port, self.path_prefix)

    def url_for(self, endpoint):
        return self._url_fmt.format(endpoint if not endpoint.startswith('/') else endpoint[1:])

    def url_for_params(self, endpoint, params):
        url = self.url_for(endpoint)
        if params:
            url += '?' + urlencode(params, True)
        return url

    @synchronized
    def _get_session(self):
        if self.__session is None:
            self.__session = self._session_factory()
            if self._imitate:
                self.__session.headers.update(IMITATE_HEADERS[self._imitate])
        return self.__session

    @property
    def session(self):
        """
        The `requests.Session <http://docs.python-requests.org/en/master/api/#requests.Session>`_ object to use for the
        next request.
        """
        with synchronized(self):
            return self._get_session()

    @session.setter
    def session(self, value):
        with synchronized(self):
            self.__session = value

    def close(self):
        with synchronized(self):
            if self.__session is not None:
                try:
                    self.__session.close()
                except Exception as e:
                    log.debug('Encountered {} while closing {}: {}'.format(type(e).__name__, self, e))
                self.__session = None

    def request(self, method, endpoint, *, raise_non_200=True, no_log=False, **kwargs):
        """
        Perform a generic request with the given HTTP method for the given endpoint.  Even id raise_non_200 is False,
        an exception may still be raised if a `requests.RequestException
        <http://docs.python-requests.org/en/master/api/#requests.RequestException>`_ was raised during processing of the
        request (default: :class:`CodeBasedRestException`)

        :param str method: HTTP method to use (GET/POST/etc.)
        :param str endpoint: A REST API endpoint
        :param dict params: URL parameters to include in the query string
        :param dict headers: Headers to send with the request
        :param bool raise_non_200: Raise an exception is the response has a non-2xx status code (default: True)
        :param bool no_log:
        :param kwargs: Args to pass to `requests.Session.request
          <http://docs.python-requests.org/en/master/api/#requests.Session.request>`_: files, data, json, auth, cookies,
          hooks, timeout
        :return requests.Response: The response as a `requests.Response
          <http://docs.python-requests.org/en/master/api/#requests.Response>`_ object
        """
        url = self.url_for(endpoint)
        if not no_log:
            suffix = ''
            if self._log_params:
                params = kwargs.get('params')
                if params:
                    suffix = '?' + urlencode(params, True)
            log.debug('{} -> {}{}'.format(method, url, suffix))
        kwargs.setdefault('verify', self._verify_ssl)
        try:
            resp = self.session.request(method, url, **kwargs)
        except requests.RequestException as e:
            raise self._exc_type(e, url)
        if raise_non_200 and not (200 <= resp.status_code <= 299):
            raise self._exc_type(resp, url)
        return resp

    def get(self, endpoint, **kwargs):
        return self.request('GET', endpoint, **kwargs)

    def put(self, endpoint, **kwargs):
        return self.request('PUT', endpoint, **kwargs)

    def post(self, endpoint, **kwargs):
        return self.request('POST', endpoint, **kwargs)

    def delete(self, endpoint, **kwargs):
        return self.request('DELETE', endpoint, **kwargs)

    def async_request(self, *args, **kwargs):
        return as_future(self.request, args, kwargs)

    def async_get(self, endpoint, **kwargs):
        return as_future(self.request, ('GET', endpoint), kwargs)

    def async_put(self, endpoint, **kwargs):
        return as_future(self.request, ('PUT', endpoint), kwargs)

    def async_post(self, endpoint, **kwargs):
        return as_future(self.request, ('POST', endpoint), kwargs)

    def async_delete(self, endpoint, **kwargs):
        return as_future(self.request, ('DELETE', endpoint), kwargs)


@atexit_register
def http_cleanup():
    with synchronized(__instances):
        for session in __instances:
            with suppress(Exception):
                session.close()
