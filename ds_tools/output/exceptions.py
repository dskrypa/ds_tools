

__all__ = ['InvalidAnsiCode', 'TableFormatException']


class InvalidAnsiCode(Exception):
    """Exception to be raised when an invalid ANSI color/attribute code is selected"""


class TableFormatException(Exception):
    def __init__(self, scope, fmt_str, value, exc, *args):
        self.scope = scope
        self.fmt_str = fmt_str
        self.value = value
        self.exc = exc
        super().__init__(*args)

    def __str__(self):
        msg_fmt = 'Error formatting {}: {} {}\nFormat string: {!r}\nContent: {}'
        return msg_fmt.format(self.scope, type(self.exc).__name__, self.exc, self.fmt_str, self.value)
