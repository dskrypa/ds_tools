"""
Facilitates preparation of log directories and configuring loggers with custom settings

:author: Doug Skrypa
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime
from logging import LogRecord, Logger, StreamHandler, Handler, Filter, Formatter
from pathlib import Path
from threading import RLock
from typing import Optional, Union, Collection, Iterable, Callable, Mapping, Any

from tzlocal import get_localzone

from .output.color import colored

__all__ = [
    'init_logging', 'add_context_filter', 'logger_has_non_null_handlers', 'ENTRY_FMT_DETAILED',
    'ENTRY_FMT_DETAILED_PID', 'ENTRY_FMT_DETAILED_PID_UID', 'ENTRY_FMT_DETAILED_UID', 'DatetimeFormatter',
    'ColorLogFormatter', 'ColorThreadFormatter', 'get_logger_info', 'stream_config_dict'
]
log = logging.getLogger(__name__)

ON_WINDOWS = os.name == 'nt'
COLOR_CODED_THREADS = os.environ.get('DS_TOOLS_COLOR_CODED_THREAD_LOGS', '0') == '1'

DEFAULT_LOG_DIR_NAME = 'script_logs'

ENTRY_FMT_DETAILED = '%(asctime)s %(levelname)s %(threadName)s %(name)s %(lineno)d %(message)s'
ENTRY_FMT_DETAILED_PID = '%(asctime)s %(levelname)s %(process)d %(threadName)s %(name)s %(lineno)d %(message)s'
ENTRY_FMT_DETAILED_UID = '%(asctime)s %(levelname)s %(threadName)s %(name)s %(lineno)d [%(uid)s] %(message)s'
ENTRY_FMT_DETAILED_PID_UID = '%(asctime)s %(levelname)s %(process)d %(threadName)s %(name)s %(lineno)d [%(uid)s] %(message)s'

SUPPRESS_WARNINGS = ('InsecureRequestWarning',)

_NotSet = object()
_lock = RLock()
_stream_refs = set()

PathLike = Union[Path, str]
Verbosity = Union[int, bool, None]
OptStrs = Optional[Collection[str]]


def init_logging(
    verbosity: Verbosity = 0,
    *,
    log_path: PathLike | None = _NotSet,
    names: OptStrs = _NotSet,
    names_add: OptStrs = _NotSet,
    date_fmt: str = None,
    millis: bool = False,
    entry_fmt: str = None,
    file_fmt: str = None,
    file_perm: int = 0o666,
    file_lvl: int = logging.DEBUG,
    file_dir: PathLike | None = None,
    filename_fmt: str = '{prog}.{user}.{time}{uniq}.log',
    file_handler_opts: Mapping[str, Any] = None,
    prog_from_sys_argv: bool = False,
    cleanup_old_files: bool = True,
    fix_sigpipe: bool = True,
    patch_emit: str = 'quiet',
    replace_handlers: bool = True,
    lvl_names: Mapping[int, str] = _NotSet,
    lvl_names_add: Mapping[int, str] = None,
    set_levels: Mapping[str, int] = None,
    streams: bool = True,
    reopen_streams: bool = False,
    color_threads: bool = None,
    capture_warnings: bool = True,
    suppress_warnings: OptStrs = _NotSet,
    suppress_additional_warnings: Collection[str] = None,
    http_debugging: bool = False,
    set_tz: bool = True,
):
    """
    Configures stream handlers for stdout and stderr so that logs with level logging.INFO and below are sent to stdout
    and logs with level logging.WARNING and above are sent to stderr.  If a log_path is provided, or if it is not
    specified, then a file handler will be added as well.  The default log file path/name is based on the name of the
    script that called this function and the current user.

    To prevent logging to file, set ``log_path=None``.

    The verbosity argument affects the log level that is set for stdout:
    - 0: 20 = logging.INFO (default)
    - 1: 19 = custom 'verbose' log level
    - 2: 10 = logging.DEBUG
    - 3: 9
    - 12: 0 = highest verbosity

    :param verbosity: Higher values increase stdout output verbosity.  Default (0) results in only allowing logging.INFO
      messages and above to go to stdout.  Higher values result in lower log levels being allowed to go to stdout.
    :param log_path: The path where logs should be written, or None to prevent logging to file.  If not specified, a
      path will be chosen based on the script that called this function and the current user.
    :param names: The names of the loggers for which handlers should be configured.  If set to None, or if not specified
      and ``verbosity`` > 10, then the root logger will be configured.  If not specified and ``verbosity`` < 10, then 2
      loggers are configured: one for ``__main__``, and one for the base logger of the package that this function is in.
    :param names_add: The names of loggers for which handlers should be configured, in addition to the default handlers.
    :param date_fmt: The `datetime format code
      <https://docs.python.org/3/library/datetime.html#strftime-and-strptime-format-codes>`_ to use for timestamps
    :param millis: Include milliseconds in the datetime format (ignored if ``date_fmt`` is specified)
    :param entry_fmt: The stream handler `log message format
      <https://docs.python.org/3/library/logging.html#logrecord-attributes>`_ to use for stdout/stderr.  If not
      specified, the default is based on the specified verbosity - '%(message)s' is used when verbosity < 3, otherwise
      :data:`ENTRY_FMT_DETAILED` is used.
    :param file_fmt: The file handler `log message format
      <https://docs.python.org/3/library/logging.html#logrecord-attributes>`_ to use for logs written to a log file.
      Defaults to :data:`ENTRY_FMT_DETAILED`.
    :param file_perm: The octal unix file permissions to set for the log file, if writing to a log file.  This is only
      used immediately after initializing the file handler - if the file rotates, the new file is not guaranteed to have
      this permission set.
    :param file_lvl: The minimum `log level <https://docs.python.org/3/library/logging.html#logging-levels>`_ that
      should be written to the log file, if configured.
    :param file_dir: Directory in which log files should be stored for automatically generated log file paths. Ignored
      if ``log_path`` is specified (default: :data:`DEFAULT_LOG_DIR_NAME` within a system-appropriate temp directory).
    :param filename_fmt: Format string to use for automatically generated log file names.  Supported variables include:
      - ``{prog}``: The name of the top-level script that is running (without its extension)
      - ``{user}``: The name of the current user
      - ``{time}``: Unix epoch timestamp
      - ``{uniq}``: Empty by default; if a file already exists with the same name, then this value will be ``-0`` or the
        first integer that results in a unique filename.
      - ``{pid}``: The pid of the current process
    :param file_handler_opts: Keyword arguments to pass to :class:`TimedRotatingFileHandler
      <logging.handlers.TimedRotatingFileHandler>`.  Overrides all arguments specified by default, except the log path.
      Defaults to ``{'when': 'midnight', 'backupCount': 7, 'encoding': 'utf-8'}``
    :param prog_from_sys_argv: If True, and logging to file with an automatically generated name is enabled, derive the
      value for ``prog`` from ``sys.argv`` (default: derive the value by inspecting the call stack)
    :param cleanup_old_files: If logging to file with an automatically generated name is enabled, then old log files
      with matching names will be cleaned up by default.  Set to ``False`` to disable.
    :param fix_sigpipe: Restores the default handler for SIGPIPE so that a closed pipe (such as when piping
      output to ``| head``) will not cause an exception.
    :param patch_emit: Patches :meth:`logging.StreamHandler.emit` to fix closed pipe behavior on Windows (such
      as when piping output to ``| head``) since the SIGPIPE handler solution does not work on Windows.  Accepts
      ``'quiet'`` (default) to silently ignore :exc:`OSError` / :exc:`BrokenPipeError`, ``True`` to re-raise those
      exceptions without attempting to continue logging the record, or ``False`` to use the original method, which
      calls :meth:`logging.Handler.handleError` to log the message and a full stack trace to stderr for every message
      that could not be written.
    :param replace_handlers: Remove any existing handlers on loggers before adding handlers to them
    :param lvl_names: Mapping of {int(level): str(name)} to set non-default log level names
    :param lvl_names_add: Additional level names to add, besides the defaults
    :param set_levels: Mapping of {str(logger name): int(level)} to set the log level for the given loggers
    :param streams: Log to stdout and stderr (default: True).
    :param reopen_streams: Reopen stdout/stderr to ensure UTF-8 output
    :param color_threads: Use :class:`ColorThreadFormatter` to color-code output for threads.  If specified, this
      overrides the ``DS_TOOLS_COLOR_CODED_THREAD_LOGS`` environment variable
    :param capture_warnings: Have the logging framework capture warnings instead of emitting them as warnings
    :param suppress_warnings: Warnings to be suppressed (only works when ``capture_warnings`` is True)
    :param suppress_additional_warnings: Warnings to be suppressed in addition to the default warnings that will be
      suppressed (only works when ``capture_warnings`` is True)
    :param http_debugging: Enable HTTP request debug logging
    :param set_tz: Whether a default value for the ``TZ`` environment variable should be set (defaults to True) to
      prevent unnecessary system calls on Linux (see
      `https://blog.packagecloud.io/set-environment-variable-save-thousands-of-system-calls/`__ for more info).
    :return: The path to which logs are being written, or None if no file handler was configured.
    """
    if set_tz:
        os.environ.setdefault('TZ', ':/etc/localtime')  # This avoids extra sys calls; see docstring for more info
    if fix_sigpipe:
        import signal
        try:
            signal.signal(signal.SIGPIPE, signal.SIG_DFL)   # Prevent error when piping output
        except AttributeError:
            pass                                            # Does not work in Windows
    if patch_emit:
        logging.StreamHandler.emit = _stream_handler_emit_quiet if patch_emit == 'quiet' else _stream_handler_emit

    _configure_level_names(lvl_names, lvl_names_add)

    if http_debugging and names_add is _NotSet:
        names_add = ['http.client', 'requests', 'urllib3']
    loggers = _get_loggers(names, verbosity, names_add, replace_handlers)
    root_logger = logging.getLogger()
    if root_logger in loggers:
        root_logger.addHandler(logging.NullHandler())       # Hide logs written directly to the root logger
    root_logger.setLevel(logging.NOTSET)                    # Default is 30 / WARNING

    date_fmt = date_fmt or ('%Y-%m-%d %H:%M:%S.%f %Z' if millis else '%Y-%m-%d %H:%M:%S %Z')    # used by all handlers
    if streams:
        _add_stream_handlers(
            loggers, verbosity, date_fmt, entry_fmt, reopen_streams=reopen_streams, color_threads=color_threads
        )

    if set_levels:
        if not isinstance(set_levels, dict):
            raise TypeError('levels must be a dict of logger_name=level pairs')
        for name, lvl in set_levels.items():
            logging.getLogger(name).setLevel(lvl)

    if log_path is not None:
        if log_path is _NotSet:
            log_path = _choose_log_path(
                file_dir, filename_fmt, cleanup_old=cleanup_old_files, prog_from_sys_argv=prog_from_sys_argv
            )
        else:
            log_path = Path(log_path).expanduser()
        _add_file_handler(loggers, log_path, date_fmt, file_fmt, file_lvl, file_handler_opts, file_perm)

    if capture_warnings:
        _capture_warnings(suppress_warnings, suppress_additional_warnings)  # noqa
    if http_debugging:
        enable_http_debug_logging()

    return log_path


def stream_config_dict(
    verbosity: Verbosity = 0,
    *,
    names: OptStrs = _NotSet,
    names_add: OptStrs = _NotSet,
    entry_fmt: str = None,
    date_fmt: str = None,
    millis: bool = False,
):
    date_fmt = date_fmt or ('%Y-%m-%d %H:%M:%S.%f %Z' if millis else '%Y-%m-%d %H:%M:%S %Z')  # used by all handlers
    entry_fmt = entry_fmt or (ENTRY_FMT_DETAILED if verbosity and verbosity > 2 else '%(message)s')
    names = _get_logger_names(names, verbosity, names_add)
    # fmt: off
    config = {
        'filters': {
            'stdout': {'()': create_filter(lambda r: r.levelno < logging.WARNING)},
            'stderr': {'()': create_filter(lambda r: r.levelno >= logging.WARNING)},
        },
        'formatters': {
            'stream': {'()': ColorLogFormatter(entry_fmt, date_fmt)},
        },
        'handlers': {
            'stdout': {
                'class': 'logging.StreamHandler',
                'formatter': 'stream',
                'level': logging.DEBUG + 2 - verbosity if verbosity else logging.INFO,
                'filters': ['stdout'],
                'stream': 'ext://sys.stdout',
            },
            'stderr': {
                'class': 'logging.StreamHandler',
                'formatter': 'stream',
                'level': logging.INFO,
                'filters': ['stderr'],
                'stream': 'ext://sys.stderr',
            },
        },
        'loggers': {
            name: {'level': logging.NOTSET, 'handlers': ['stdout', 'stderr']} for name in names if name
        },
    }
    if None in names:
        config['root'] = {'level': logging.NOTSET, 'handlers': ['stdout', 'stderr']}
    # fmt: on
    return config


def _add_stream_handlers(
    loggers: Iterable[Logger],
    verbosity: Union[int, bool],
    date_fmt: str,
    entry_fmt: Optional[str] = None,
    stdout_lvl_filter: Optional[Callable] = None,
    stderr_lvl_filter: Optional[Callable] = None,
    reopen_streams: bool = True,
    color_threads: bool = False,
):
    entry_fmt = entry_fmt or (ENTRY_FMT_DETAILED if verbosity and verbosity > 2 else '%(message)s')

    stdout = open(sys.stdout.fileno(), mode='w', encoding='utf-8', buffering=1) if reopen_streams else sys.stdout
    stdout_handler = logging.StreamHandler(stdout)
    stdout_handler.setLevel(logging.DEBUG + 2 - verbosity if verbosity else logging.INFO)
    stdout_handler.addFilter(stdout_lvl_filter or create_filter(lambda r: r.levelno < logging.WARNING))
    stdout_handler.name = 'stdout'

    stderr = open(sys.stderr.fileno(), mode='w', encoding='utf-8', buffering=1) if reopen_streams else sys.stderr
    stderr_handler = logging.StreamHandler(stderr)
    stderr_handler.setLevel(logging.INFO)
    stderr_handler.addFilter(stderr_lvl_filter or create_filter(lambda r: r.levelno >= logging.WARNING))
    stderr_handler.name = 'stderr'

    if color_threads or (COLOR_CODED_THREADS and color_threads is not False):
        stream_formatter = ColorThreadFormatter(entry_fmt, date_fmt)
    else:
        stream_formatter = ColorLogFormatter(entry_fmt, date_fmt)
    stream_handlers = (stdout_handler, stderr_handler)
    for handler in stream_handlers:
        handler.setFormatter(stream_formatter)
    for logger in loggers:
        for handler in stream_handlers:
            logger.addHandler(handler)


def _find_prog_name(use_sys_argv: bool = False) -> str:
    if use_sys_argv:
        try:
            return Path(sys.argv[0]).stem
        except (IndexError, TypeError, AttributeError):
            pass

    import inspect

    # Traceback = namedtuple('Traceback', 'filename lineno function code_context index')
    # FrameInfo = namedtuple('FrameInfo', ('frame',) + Traceback._fields)
    stack = inspect.stack()
    top_file = stack[-1].filename
    if not top_file.startswith('<'):
        return Path(top_file).stem
    # stack[0] = this function
    # stack[1] = _choose_log_path
    # stack[2] = init_logging
    # stack[3] => is therefore presumably from the file that called init_logging
    return Path(stack[3].filename).stem


def _choose_log_path(
    file_dir: PathLike, filename_fmt: str, cleanup_old: bool = True, prog_from_sys_argv: bool = False
) -> Path:
    import time
    from getpass import getuser

    log_dir = Path(file_dir) if file_dir else _get_default_user_log_dir()
    try:
        prog = _find_prog_name(prog_from_sys_argv)
    except (TypeError, AttributeError, IndexError):
        prog = f'{Path(__file__).stem}_interactive'

    name_parts = {
        'prog': prog, 'user': getuser(), 'time': int(time.time()), 'uniq': '', 'pid': os.getpid(), 'ppid': os.getppid()
    }
    log_path = log_dir.joinpath(filename_fmt.format(**name_parts))
    if '{uniq}' in filename_fmt and log_path.exists():
        from itertools import count

        suffix = count()
        while log_path.exists():
            name_parts['uniq'] = f'-{next(suffix)}'
            log_path = log_dir.joinpath(filename_fmt.format(**name_parts))

    if cleanup_old and any(ph in filename_fmt for ph in ('{time}', '{pid}', '{ppid}')) and log_dir.exists():
        _cleanup_old_log_files(log_dir, filename_fmt, name_parts, 14 if cleanup_old is True else cleanup_old)

    return log_path


def _cleanup_old_log_files(log_dir: Path, name_fmt: str, name_parts: dict[str, str | int], del_age_days: int):
    import re
    import time
    from stat import S_ISREG

    name_parts.update(time=r'(\d+)', uniq=r'\-?\d*', pid=r'\d+', ppid=r'\d+')
    use_name_time = '{time}' in name_fmt
    escaped_fmt = re.escape(name_fmt).replace('\\{', '{').replace('\\}', '}')
    # Note: If this code survives beyond year 2100, the following date suffix pattern will need to be updated!
    log_fmt_match = re.compile('^' + escaped_fmt.format(**name_parts) + r'(?:\.20\d\d-[01]\d-[0-3]\d)?$').match
    current_time = int(time.time())
    delta_seconds = del_age_days * 86400  # = 60 * 60 * 24
    for path in log_dir.iterdir():
        try:
            stat_info = path.stat()
        except OSError:
            continue
        if not S_ISREG(stat_info.st_mode):
            continue
        m = log_fmt_match(path.name)
        if m and (current_time - (int(m.group(1)) if use_name_time else stat_info.st_mtime)) > delta_seconds:
            try:
                path.unlink()
            except OSError as e:
                log.error(f'Error deleting old log file: {path} - {e}')


def _get_default_user_log_dir() -> Path:
    from getpass import getuser
    from tempfile import gettempdir

    path = Path(gettempdir())
    if not ON_WINDOWS or not path.as_posix().endswith('AppData/Local/Temp'):
        path = path.joinpath(getuser())
    if ON_WINDOWS and path.resolve().drive != 'C:' and (log_dir := Path(f'C:{path.as_posix()}')).exists():
        path = log_dir

    path = path.joinpath(DEFAULT_LOG_DIR_NAME)
    if not path.exists():
        path.mkdir(parents=True, exist_ok=True)
    return path


def _add_file_handler(
    loggers: Iterable[Logger],
    log_path: Path,
    date_fmt: str,
    file_fmt: str,
    file_lvl: int,
    file_handler_opts: Mapping[str, Any],
    file_perm: int,
):
    from logging.handlers import TimedRotatingFileHandler

    log_path = log_path.as_posix()
    prep_log_dir(log_path)
    file_handler_opts = file_handler_opts or {'when': 'midnight', 'backupCount': 7, 'encoding': 'utf-8'}
    file_handler = TimedRotatingFileHandler(log_path, **file_handler_opts)
    try:
        os.chmod(log_path, file_perm)
    except OSError:
        pass
    file_handler.setLevel(file_lvl)
    file_handler.setFormatter(DatetimeFormatter(file_fmt or ENTRY_FMT_DETAILED, date_fmt))
    file_handler.name = log_path
    for logger in loggers:
        logger.addHandler(file_handler)
    log.log(19, f'Logging to {log_path}')


def _get_logger_names(
    names: OptStrs = _NotSet,
    verbosity: Verbosity = 0,
    names_add: OptStrs = _NotSet,
) -> set[Optional[str]]:
    if names is _NotSet:
        if verbosity and verbosity > 10:
            names = {None}
        else:
            names = {__name__.split('.')[0], '__main__', '__mp_main__', 'py.warnings'}
    elif names is None or isinstance(names, str):
        names = {names}

    if names_add is not _NotSet:
        names.update({names_add} if names_add is None or isinstance(names_add, str) else names_add)

    if None in names:
        names = {None}

    return names


def _get_loggers(names: OptStrs, verbosity: Verbosity, names_add: OptStrs, replace_handlers: bool) -> list[Logger]:
    loggers = list(map(logging.getLogger, _get_logger_names(names, verbosity, names_add)))
    for logger in loggers:
        logger.setLevel(logging.NOTSET)  # Let handlers deal with log levels
        if replace_handlers:
            with _lock:  # Prevent stdout/stderr from being closed
                _stream_refs.update(h.stream for h in logger.handlers if isinstance(h, logging.StreamHandler))
            logger.handlers = []

    return loggers


def _capture_warnings(warnings: OptStrs = _NotSet, additional: OptStrs = None):
    logging.captureWarnings(True)
    warnings = set(SUPPRESS_WARNINGS) if warnings is _NotSet else set(warnings) if warnings else set()
    if additional:
        warnings.update(additional)

    class WarningFilter(logging.Filter):
        if sys.version_info[:2] > (3, 11):  # The behavior changed between 3.10 and 3.11
            def filter(self, record):
                try:
                    msg = record.args[0]
                    return not any(w in msg for w in warnings)
                except Exception:  # noqa
                    return True
        else:
            def filter(self, record):
                try:
                    return not any(w in record.msg for w in warnings)
                except Exception:  # noqa
                    return True

    logging.getLogger('py.warnings').addFilter(WarningFilter())


def _configure_level_names(lvl_names: Mapping[int, str] = _NotSet, lvl_names_add: Mapping[int, str] = None):
    if lvl_names is _NotSet:
        lvl_names = {lvl: f'DBG_{lvl}' for lvl in range(1, 10)}
        lvl_names.update({lvl: f'Lv_{lvl}' for lvl in range(11, 19)})
        lvl_names[19] = 'VERBOSE'
    if lvl_names_add:
        lvl_names = lvl_names or {}
        lvl_names.update(lvl_names_add)
    if lvl_names:
        for lvl, name in lvl_names.items():
            if (name not in logging._nameToLevel) and (lvl not in logging._levelToName):  # noqa
                logging.addLevelName(lvl, name)


def enable_http_debug_logging():
    import http.client as http_client
    from urllib3.connection import HTTPConnection, HTTPSConnection

    http_client_logger = logging.getLogger('http.client')

    def _http_log(*args):
        http_client_logger.debug(' '.join(args))

    http_client.print = _http_log
    for cls in (http_client.HTTPConnection, http_client.HTTPSConnection, HTTPConnection, HTTPSConnection):
        cls.debuglevel = property(lambda s: 1, lambda s, level: None)
        cls.set_debuglevel = lambda level: None

    for name in ('requests.packages.urllib3', 'urllib3', 'requests'):
        logger = logging.getLogger(name)
        logger.setLevel(logging.NOTSET)
        logger.setLevel = lambda level: None  # prevent other libs from changing these levels
        logger.propagate = True


def create_filter(filter_fn: Callable[[LogRecord], bool]) -> Filter:
    """
    Uses the given function to filter log entries based on level number.  The function should return True if the
    record should be logged, or False to ignore it.

    The decompilation was mostly an exercise to see what was possible; it's obviously not necessary for the
    functionality of this class/method

    :param filter_fn: A function that takes 1 parameter (record) and returns a boolean
    :return: A custom, initialized subclass of logging.Filter using the given filter function
    """
    class CustomLogFilter(Filter):
        def filter(self, record: LogRecord) -> bool:
            return filter_fn(record)

    return CustomLogFilter()


class DatetimeFormatter(Formatter):
    """Enables use of ``%f`` (micro/milliseconds) in datetime formats."""
    _local_tz = get_localzone()

    def formatTime(self, record: LogRecord, datefmt: str = None) -> str:
        dt = datetime.fromtimestamp(record.created, self._local_tz)
        if datefmt:
            return dt.strftime(datefmt)
        else:
            return self.default_msec_format % (dt.strftime(self.default_time_format), record.msecs)


class ColorLogFormatter(DatetimeFormatter):
    """
    Uses ANSI escape codes to colorize stdout/stderr logging output.  Colors may be specified by using the ``extra``
    parameter when logging, for example::\n
        log.error('An error occurred', extra={'color': 'red'})
    """

    def format(self, record: LogRecord) -> str:
        formatted = super().format(record)
        color = getattr(record, 'color', None)
        if color:
            if isinstance(color, (str, int)):
                formatted = colored(formatted, color)
            elif isinstance(color, dict):
                formatted = colored(formatted, **color)
            else:
                formatted = colored(formatted, *color)  # noqa
        return formatted


class ColorThreadFormatter(ColorLogFormatter):
    """Use a different color for each thread's logged messages."""

    def format(self, record: LogRecord) -> str:
        formatted = super().format(record)
        try:
            thread_num = int(record.threadName.split('-')[1])
        except Exception:  # noqa
            pass
        else:
            color_num = thread_num % 256
            while color_num in (0, 16, 17, 18, 19, 232, 233, 234, 235, 236, 237):
                color_num += 51
                if color_num > 255:
                    color_num %= 256
            formatted = colored(formatted, color_num)
        return formatted


def prep_log_dir(log_path: PathLike, perm_change_prefix: str = '/var/tmp/', new_dir_permissions: int | None = 0o1777):
    """
    Creates any necessary intermediate directories in order for the given log path to be valid.  Log directory's
    permissions default to 1777 (sticky, read/write/exec for everyone).

    :param log_path: Log file destination
    :param perm_change_prefix: Apply new_dir_permissions to the dir if it needs to be created and starts with this
    :param new_dir_permissions: Octal permissions for the new directory if it needs to be created.
    """
    log_dir = log_path.parent if isinstance(log_path, Path) else Path(log_path).parent
    if log_dir.exists():
        if not log_dir.is_dir():
            raise ValueError(f'Invalid log path - {log_dir} is not a directory')
    else:
        log_dir.mkdir(parents=True, exist_ok=True)
        if new_dir_permissions is not None and log_dir.as_posix().startswith(perm_change_prefix):
            try:
                log_dir.chmod(new_dir_permissions)
            except OSError as e:
                log.error(f'Error changing permissions for {log_dir} to 0o{new_dir_permissions:o}: {e}')


def add_context_filter(filter_instance: Filter, name: str = None):
    """
    :param filter_instance: An instance of the :class:`logging.Filter` class that should be used
    :param name: None to add to all loggers, or a string that is the prefix of all loggers that should use the given
      filter
    """
    for logger_name, logger in Logger.manager.loggerDict.items():
        if (name is None) or (isinstance(logger_name, str) and logger_name.startswith(name)):
            try:
                logger.addFilter(filter_instance)
            except AttributeError:                  # ignore PlaceHolder objects
                pass


def update_level(name: str, level: int, verbosity: str = 'set', handlers: bool = True, handlers_only: bool = False):
    """
    Recursively update loggers and their handlers to change the level of logs that are emitted.

    :param name: Logger name
    :param level: Log level
    :param verbosity: One of ('set', 'increase', 'decrease', '+', '-') to indicate whether the log level should
      change or not based on the current level
    :param handlers: Change the level of handlers (if False: only change the level of loggers)
    :param handlers_only: True to only change the level of handlers, False (default) to change the level of
      handlers and loggers (note: ``handlers`` must also be True to change the level of handlers - if ``handlers`` is
      False and ``handlers_only`` is True, then no actions will be taken)
    """
    lv_name = logging.getLevelName
    v, lv = verbosity, level
    logger = logging.getLogger(name)
    n = logger.level
    if not handlers_only:
        if (n != lv and v == 'set') or (n > lv and v in ('increase', '+')) or (n > lv and v in ('decrease', '-')):
            log.info(f'Updating log level for {logger!r} from {n} ({lv_name(n)}) to {level} ({lv_name(level)})')
            logger.setLevel(level)

    if handlers and hasattr(logger, 'handlers'):
        for handler in logger.handlers:
            n = handler.level
            if (n != lv and v == 'set') or (n > lv and v in ('increase', '+')) or (n > lv and v in ('decrease', '-')):
                log.info(f"Updating log level for {logger=} {handler=} from {n} ({lv_name(n)}) to {lv} ({lv_name(lv)})")
                handler.setLevel(level)

    if name is not None and '.' in name:
        update_level(name.rsplit('.', 1)[0], level, verbosity, handlers)


def get_logger_info(only_with_handlers: bool = False, non_null_handlers_only: bool = False, test_filters: bool = False):
    from collections import ChainMap

    loggers = {}
    for lname, logger in ChainMap(Logger.manager.loggerDict, {None: logging.getLogger()}).items():
        entry = {'type': type(logger).__qualname__}
        try:
            entry['level'] = logger.level
            entry['level_name'] = logging.getLevelName(logger.level)
        except AttributeError:
            pass

        if hasattr(logger, 'handlers'):
            handlers = []
            for handler in logger.handlers:
                if non_null_handlers_only and isinstance(handler, logging.NullHandler):
                    continue

                handler_info = {
                    'type': type(handler).__qualname__,
                    'name': handler.name,
                    'level': handler.level,
                    'level_name': logging.getLevelName(handler.level),
                }
                if isinstance(handler, logging.FileHandler):
                    handler_info['file'] = handler.baseFilename
                elif isinstance(handler, logging.StreamHandler):    # FileHandler is a StreamHandler
                    handler_info['stream'] = getattr(handler.stream, 'name', '')
                if handler.formatter:
                    handler_info['formatter'] = {
                        'type': type(handler.formatter).__qualname__,
                        'format': handler.formatter._fmt,
                        'date_format': handler.formatter.datefmt
                    }
                if handler.filters:
                    if test_filters:
                        record = logging.LogRecord(lname, 0, 'test', 1, 'test', None, None)
                        filter_info = []
                        for f in handler.filters:
                            allowed = []
                            for i in range(51):
                                record.levelno = i
                                record.levelname = logging.getLevelName(i)
                                if f.filter(record):
                                    allowed.append(i)

                            filter_info.append({
                                'type': type(f).__qualname__,
                                'repr': repr(f),
                                'level_range': (min(allowed), max(allowed))
                            })
                    else:
                        filter_info = [{'type': type(f).__qualname__, 'repr': repr(f)} for f in handler.filters]

                    handler_info['filters'] = filter_info
                handlers.append(handler_info)

            if handlers:
                entry['handlers'] = handlers
            elif only_with_handlers:
                continue
        elif only_with_handlers:
            continue

        loggers[lname or '__root__'] = entry

    return loggers


def get_level_info(handler: Handler) -> str:
    """
    :param handler: An instance of a logging handler object
    :return: A string representation of the handler's logging level and its filters
    """
    htype = f'{handler.__class__.__module__}.{handler.__class__.__name__}'
    if hasattr(handler, 'stream') and hasattr(handler.stream, 'name'):
        sname = handler.stream.name
        htype += sname if (sname.startswith('<') and sname.endswith('>')) else f'<{sname}>'
    return f'{htype}: {handler.level} ({logging.getLevelName(handler.level)})'


def get_levels(logger: Logger) -> list[str]:
    """
    :param logger: A Logger
    :return: A list of information about the given logger's handlers from :func:`get_level_info`
    """
    return [
        f'base: {logger.level} ({logging.getLevelName(logger.level)})', *(get_level_info(h) for h in logger.handlers)
    ]


def _stream_handler_emit(self: StreamHandler, record: LogRecord):
    # This monkey patch is to fix handling of piped output on Windows
    try:
        msg = self.format(record)
        stream = self.stream
        # issue 35046: merged two stream.writes into one.
        stream.write(msg + self.terminator)
        self.flush()
    except RecursionError:  # See issue 36272
        raise
    except (BrokenPipeError, OSError):  # Occurs when using |head
        raise
    except Exception:  # noqa
        self.handleError(record)


def _stream_handler_emit_quiet(self: StreamHandler, record: LogRecord):
    # This monkey patch is to fix handling of piped output on Windows
    try:
        msg = self.format(record)
        stream = self.stream
        # issue 35046: merged two stream.writes into one.
        stream.write(msg + self.terminator)
        self.flush()
    except RecursionError:  # See issue 36272
        raise
    except (BrokenPipeError, OSError):  # Occurs when using |head
        pass
    except Exception:  # noqa
        self.handleError(record)


def logger_has_non_null_handlers(logger: Logger) -> bool:
    # Based on logging.Logger.hasHandlers(), but checks that they are not all NullHandlers
    c = logger
    rv = False
    while c:
        if c.handlers and not all(isinstance(h, logging.NullHandler) for h in c.handlers):
            rv = True
            break
        if not c.propagate:
            break
        else:
            c = c.parent
    return rv
