"""
Exceptions and warnings for the caching package.

:author: Doug Skrypa
"""

__all__ = ['CacheLockWarning']


class CacheLockWarning(Warning):
    def __init__(self, func, lock):
        self.func = func
        self.lock = lock

    def __str__(self):
        msg_fmt = 'The @cached lock provided for method {!r} appears to be a single lock instance: {}'
        return msg_fmt.format(self.func.__qualname__, self.lock)
