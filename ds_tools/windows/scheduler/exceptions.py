
from ..com.exceptions import ComException, ComClassCreationException
from .constants import REGISTER_TASK_ERROR_CODES

__all__ = ['UnknownTaskError', 'TaskCreationException']


class UnknownTaskError(ComException):
    pass


class TaskCreationException(ComClassCreationException):
    def __init__(self, com_error, path, name, cron, cmd, args):
        self._error = com_error
        self.path, self.name, self.cron, self.cmd, self._args = path, name, cron, cmd, args

    def _message(self):
        hr, msg, exc, arg = self._error.args
        error_code = exc[5] + 2 ** 32
        try:
            return REGISTER_TASK_ERROR_CODES[error_code]
        except KeyError:
            return f'Unknown error_code={hex(error_code)}'

    def __str__(self):
        return f'{self.__class__.__name__}: {self._message()} [{self._error}]'
