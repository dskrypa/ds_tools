"""
HTTP / REST Exceptions

:author: Doug Skrypa
"""

__all__ = [
    'CodeBasedRestException', 'SimpleRestException', 'UnauthorizedRestException', 'UnavailableRestException',
    'http_code_and_reason',
]


def http_code_and_reason(cause):
    """
    Determines the HTTP response code and its associated string representation based on the given Exception or Response.

    :param cause: An Exception of :class:`requests.Response` object
    :return tuple: (int(code), str(reason)) if possible, otherwise (None, None)
    """
    try:
        lc_codes = http_code_and_reason._lc_codes
    except AttributeError:
        from requests.status_codes import codes
        lc_codes = http_code_and_reason._lc_codes = {
            '{} {}'.format(c, reason.lower().replace('_', ' ')): c for reason, c in codes.__dict__.items()
        }

    if isinstance(cause, Exception):
        lc_err = str(cause).lower()
        for r, c in lc_codes.items():
            if r in lc_err:
                return c, r[4:].title()
    else:
        try:
            return cause.status_code, cause.reason
        except AttributeError:
            pass
    return None, None


class SimpleRestException(Exception):
    """
    A simple, standalone REST Exception that extracts the HTTP code & reason from the reason for being raised

    If the cause is a Response object from a requests lib Request, then the code and reason are extracted from it.  If
    the cause is an exception, then the str representation of the exception is examined fro HTTP status codes.  If a
    match for '{code} {reason}' is found, then that code + reason are assumed to be the root cause.

    :param cause: An Exception or a :class:`requests.Response` object
    :param str endpoint: The REST endpoint that was called and generated the response that prompted this Exception
    :param args: Additional args to pass to the Exception constructor, including an optional message first parameter
    """
    def __init__(self, cause, endpoint, *args):
        self.code, self.reason = http_code_and_reason(cause)
        self.endpoint = endpoint
        if isinstance(cause, Exception):
            self.resp = None
            self.exception = cause
            self.msg = args[0] if len(args) > 0 else str(cause)
        else:
            self.resp = cause
            self.exception = None
            self.msg = None
            if len(args) > 0:
                self.msg = args[0]
            if not self.msg:
                txt = self.resp.text
                if isinstance(txt, str) and ((len(txt.splitlines()) < 6) and (len(txt) < 500)):
                    self.msg = self.resp.text
        super().__init__(*args)

    def __str__(self):
        if self.msg:
            return '{} [{}] {} on {}: {}'.format(type(self).__name__, self.code, self.reason, self.endpoint, self.msg)
        return '{} [{}] {} on {}'.format(type(self).__name__, self.code, self.reason, self.endpoint)

    __repr__ = __str__


class CodeBasedRestException(Exception):
    """
    A REST Exception that extracts the HTTP code & reason from the reason for being raised.

    If the cause is a Response object from a requests lib Request, then the code and reason are extracted from it.  If
    the cause is an exception, then the str representation of the exception is examined fro HTTP status codes.  If a
    match for '{code} {reason}' is found, then that code + reason are assumed to be the root cause.

    If a CodeBasedRestException is raised when a more specific exception (that is a subclass of CodeBasedRestException)
    exists for the given cause's status code, then the more specific subclass will be returned by __new__.  Subclasses
    must define a `_code` property that matches an HTTP status code in order to be used in this manner.

    :param cause: An Exception or a :class:`requests.Response` object
    :param str endpoint: The REST endpoint that was called and generated the response that prompted this Exception
    :param args: Additional args to pass to the Exception constructor, including an optional message first parameter
    """
    _types = {}

    def __init_subclass__(cls):
        try:
            # noinspection PyUnresolvedReferences
            cls._types[cls._code] = cls
        except AttributeError:
            pass

    def __new__(cls, cause, endpoint, *args):
        code, reason = http_code_and_reason(cause)
        if (cls is CodeBasedRestException) and (code in cls._types):
            obj = super(CodeBasedRestException, cls).__new__(cls._types.get(code, cls))
        else:
            obj = super(CodeBasedRestException, cls).__new__(cls)
        obj.code = code
        obj.reason = reason
        return obj

    def __init__(self, cause, endpoint, *args):
        self.endpoint = endpoint
        if isinstance(cause, Exception):
            self.resp = None
            self.exception = cause
            self.msg = args[0] if len(args) > 0 else str(cause)
        else:
            self.resp = cause
            self.exception = None
            self.msg = None
            if len(args) > 0:
                self.msg = args[0]
            if not self.msg:
                txt = self.resp.text
                if isinstance(txt, str) and ((len(txt.splitlines()) < 6) and (len(txt) < 500)):
                    self.msg = self.resp.text
        super(CodeBasedRestException, self).__init__(*args)

    def __reduce__(self):
        """Makes pickle work properly; implementing __getnewargs__ was not working"""
        new_args = (self.exception or self.resp, self.endpoint)
        state = self.__dict__.copy()
        state['args'] = self.args       # args does not seem to show up in __dict__ for exceptions...
        return CodeBasedRestException, new_args, state

    def __setstate__(self, state):
        self.__dict__.update(state)

    def __str__(self):
        if self.msg:
            return '{} [{}] {} on {}: {}'.format(type(self).__name__, self.code, self.reason, self.endpoint, self.msg)
        return '{} [{}] {} on {}'.format(type(self).__name__, self.code, self.reason, self.endpoint)

    __repr__ = __str__


class UnauthorizedRestException(CodeBasedRestException):
    """Exception to be raised when there is an issue with REST authentication"""
    _code = 401


class UnavailableRestException(CodeBasedRestException):
    """Exception to be raised when the REST service is unavailable"""
    _code = 503
