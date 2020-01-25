"""
:author: Doug Skrypa
"""

__all__ = ['WikiResponseError', 'PageMissingError']


class WikiResponseError(Exception):
    """Exception to be raised when a wiki responds with an error"""


class PageMissingError(Exception):
    """Exception to be raised if the requested page does not exist"""
    def __init__(self, title, host, extra=None):
        self.title = title
        self.host = host
        self.extra = extra

    def __str__(self):
        if self.extra:
            return f'No page found for {self.title!r} in {self.host} {self.extra}'
        return f'No page found for {self.title!r} in {self.host}'
