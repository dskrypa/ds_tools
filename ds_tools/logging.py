#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Facilitates preparation of log directories and configuring loggers with custom settings

:author: Doug Skrypa
"""

import getpass
import inspect
import logging
import os
import signal
import sys
import time
from contextlib import suppress
from datetime import datetime
from logging import handlers

from termcolor import colored

from .utils import validate_or_make_dir, TZ_LOCAL

__all__ = ["LogManager", "add_context_filter"]
log = logging.getLogger("ds_tools.logging")

ENTRY_FMT_DETAILED = "%(asctime)s %(levelname)s %(threadName)s %(name)s %(lineno)d %(message)s"
DEFAULT_LOGGER_NAME = "ds_tools"

COLOR_CODED_THREADS = os.environ.get("DS_TOOLS_COLOR_CODED_THREAD_LOGS", "0") == "1"


class _NotSet:
    pass


class LogManager:
    """
    Facilitates initializing the Python logger with preferred options.  Provides additional named logging functions for
    custom levels (such as "verbose").

    Intended to be initialized via :func:`LogManager.create_default_logger`

    Convenience class to manage the settings that I use most frequently for logging in Python
    """
    default_log_dir = "/var/tmp/script_logs"
    __instances = {}

    def __new__(cls, name=None, *args, **kwargs):
        if name not in cls.__instances:
            inst = super(LogManager, cls).__new__(cls)
            inst.__initialized = False
            cls.__instances[name] = inst
        return cls.__instances[name]

    def __init__(self, name=None, entry_fmt=None, date_fmt=None, replace_handlers=True, file_fmt=None, no_pipe_err=True):
        if not self.__initialized:
            if no_pipe_err:
                try:
                    signal.signal(signal.SIGPIPE, signal.SIG_DFL)   # Prevent error when piping output
                except AttributeError as e:
                    pass                                            # Does not work in Windows
            self.name = name
            self.log_funcs = {}
            self.defaults = {
                "entry_format": entry_fmt or "%(message)s",
                "date_format": date_fmt or "%Y-%m-%d %H:%M:%S %Z",
                "file_fmt": file_fmt or ENTRY_FMT_DETAILED
            }
            logging.getLogger().setLevel(logging.NOTSET)
            self.logger = logging.getLogger(name)
            self.logger.setLevel(logging.NOTSET)    #Default is 30 / WARNING
            if replace_handlers:
                self.logger.handlers = []
            self.stdout_lvl = logging.INFO
            self.log_path = None

            for fn in ("debug", "info", "warning", "error", "critical", "exception", "log"):
                setattr(self, fn, getattr(self.logger, fn))
                self.log_funcs[fn] = getattr(self, fn)
            with suppress(AttributeError):
                self.add_level(19, "VERBOSE", "verbose")
            for lvl in range(1, 10):
                with suppress(AttributeError):
                    self.add_level(lvl, "DBG_{}".format(lvl), "debug{}".format(lvl))
            for lvl in range(11, 19):
                logging.addLevelName(lvl, "Lv_{}".format(lvl))

            self.__initialized = True

    @classmethod
    def create_default_logger(cls, verbosity=0, log_path=_NotSet, name=_NotSet, entry_fmt=None, levels=None, **kwargs):
        """
        Creates a LogManager and runs :func:`LogManager.init_default_stream_logger` and
         :func:`LogManager.init_default_file_logger` to initialize stdout/stderr + file handlers.

        To prevent logging to file, set log_path=None.

        The verbosity argument affects the log level that is set for stdout:
        - 0: 20 = logging.INFO (default)
        - 1: 19 = custom "verbose" log level
        - 2: 10 = logging.DEBUG
        - 3: 9
        - 12: 0 = highest verbosity

        If the `name` argument is not provided, and verbosity is 10 or higher, then the root logger will be used instead
        of the default that would otherwise be used.

        :param int verbosity: Higher values increase verbosity
        :param log_path: Path to log file destination (default: use default location); None for no log file
        :param name: Logger name (default: `DEFAULT_LOGGER_NAME` if verbosity <= 10, None if verbosity > 10)
        :param str entry_fmt: Log entry format for streams (defaults to "%(message)s")
        :param dict levels: Mapping of {logger_name: log_level}s to set, e.g., ``{"ds_tools.logging":"DEBUG"}``
        :param kwargs: Keyword args to be passed to the LogManager constructor
        :return LogManager: LogManager instance initialized with the given/default parameters
        """
        if verbosity and verbosity > 2 and entry_fmt is None:
            entry_fmt = ENTRY_FMT_DETAILED
        if name is _NotSet:
            name = None if verbosity and (verbosity > 10) else DEFAULT_LOGGER_NAME
        lm = LogManager(name, entry_fmt=entry_fmt, **kwargs)
        lm.init_default_stream_logger(verbosity)
        if log_path is not None:
            lm.init_default_file_logger(log_path)
            log.log(19, "Logging to {}".format(lm.log_path))
        if levels:
            if not isinstance(levels, dict):
                raise TypeError("levels must be a dict of logger_name=level pairs")
            for logger_name, level in levels.items():
                logging.getLogger(logger_name).setLevel(level)
        return lm

    def get_levels(self):
        """
        :return: A list of information about this LogManager's logger's handlers from get_level_info
        """
        levels = [get_level_info(handler) for handler in self.logger.handlers]
        levels.insert(0, "base: {} ({})".format(self.logger.level, logging.getLevelName(self.logger.level)))
        return levels

    def add_level(self, level_number, level_name, fn_name=None):
        """
        Example usage: ``lm.add_level(19, "VERBOSE", "verbose")``

        :param level_number: Log level numeric value (10: debug, 20: info, 30: warning, 40: error, 50: critical)
        :param level_name: Name of the level to add to the logging module
        :param fn_name: (optional) Function name if not the same as level_name (becomes an attribute of this LogManager)
        """
        fn_name = fn_name if fn_name is not None else level_name
        try:
            getattr(self, fn_name)
        except AttributeError:
            if (level_name not in logging._nameToLevel) and (level_number not in logging._levelToName):
                logging.addLevelName(level_number, level_name)
            self._add_log_function(level_number, fn_name)
        else:
            raise AttributeError("This LogManager already has a method called '{}'".format(fn_name))

    def _add_log_function(self, level_number, fn_name):
        """
        :param level_number: Log level numeric value (10: debug, 20: info, 30: warning, 40: error, 50: critical)
        :param fn_name: Function name to add to this LogManager instance
        """
        def _log(*args, **kwargs):
            self.logger.log(level_number, *args, **kwargs)

        setattr(self, fn_name, _log)
        self.log_funcs[fn_name] = getattr(self, fn_name)

    def add_handler(self, destination, level=logging.INFO, fmt=None, date_fmt=None, filter=None, rotate=True, formatter=None, file_perm=0o666, name=None, encoding="utf-8"):
        """
        Creates a logging.Handler based on the input parameters, and adds it to this LogManager's logger

        :param destination: A stream or path destination for logged events
        :param int level: Minimum log level for this logger
        :param str fmt: Log entry format
        :param str date_fmt: Format string for timestamps
        :param filter: An instance of logging.Filter
        :param bool rotate: Use TimedRotatingFileHandler when given a log path if True, otherwise use FileHandler
        :param formatter: Uninstantiated custom logging.Formatter class, otherwise logging.Formatter is used
        :param int file_perm: File permission to set for log files
        :param str name: A name for this handler
        :param str encoding: Encoding to use for file handlers (default: utf-8)
        """
        entry_fmt = fmt if fmt is not None else self.defaults["entry_format"]
        date_fmt = date_fmt if date_fmt is not None else self.defaults["date_format"]
        formatter = formatter if formatter is not None else DatetimeFormatter

        if hasattr(destination, "write"):
            handler = logging.StreamHandler(destination)
        else:
            destination = os.path.expanduser(destination)
            prep_log_dir(destination)
            if rotate:
                handler = handlers.TimedRotatingFileHandler(destination, "midnight", backupCount=7, encoding=encoding)
            else:
                handler = logging.FileHandler(destination, encoding=encoding)
            with suppress(OSError):
                os.chmod(destination, file_perm)

        handler.setLevel(level)
        handler.setFormatter(formatter(entry_fmt, date_fmt))
        if filter is not None:
            handler.addFilter(filter)
        if name is not None:
            handler.name = name
        self.logger.addHandler(handler)

    def init_default_stream_logger(self, verbosity=0):
        """
        Initialize a logger that sends INFO messages and below to stdout and WARNING messages and above to stderr

        :param int verbosity: Higher values increase verbosity
        """
        stderr_filter = create_filter(lambda lvl: lvl >= logging.WARNING)
        stdout_filter = create_filter(lambda lvl: lvl < logging.WARNING)
        if verbosity:
            self.stdout_lvl = logging.DEBUG + 2 - verbosity     # True == 1; higher val -> lower debug level
        red_formatter = create_formatter(lambda rec: getattr(rec, "red", False), lambda msg: colored(msg, "red"))
        stdout = open(sys.stdout.fileno(), mode="w", encoding="utf-8", buffering=1)
        stderr = open(sys.stderr.fileno(), mode="w", encoding="utf-8", buffering=1)
        self.add_handler(stdout, self.stdout_lvl, filter=stdout_filter, formatter=ColorLogFormatter, name="stdout")
        self.add_handler(stderr, filter=stderr_filter, formatter=red_formatter, name="stderr")

    def init_default_file_logger(self, log_path=None, file_level=logging.DEBUG, file_fmt=None):
        """
        Initialize a logger that saves all logs to a file.

        :param str log_path: (optional) Path to log file destination, otherwise a default filename is used
        :param int file_level: Lowest log level to include in the file (default: DEBUG)
        :param str file_fmt: Log entry format string
        :return: Actual path that will be used for logging
        """
        file_fmt = file_fmt or self.defaults["file_fmt"]

        if log_path is None or log_path is _NotSet:
            this_file = os.path.splitext(os.path.basename(__file__))[0]
            calling_module = this_file
            i = 1
            while calling_module == this_file:
                try:
                    calling_module = os.path.splitext(os.path.basename(inspect.getsourcefile(inspect.stack()[1][0])))[0]
                except (TypeError, AttributeError):
                    calling_module = "{}_interactive".format(this_file)
                except IndexError:
                    break
                i += 1

            log_name_base = "{}.{:s}.{:d}".format(calling_module, getpass.getuser(), int(time.time()))
            log_path = os.path.join(self.default_log_dir, "{}.log".format(log_name_base))
            t = 0
            while os.path.exists(log_path):
                log_path = os.path.join(self.default_log_dir, "{}-{}.log".format(log_name_base, t))
                t += 1
        self.add_handler(log_path, file_level, file_fmt, rotate=True)
        self.log_path = log_path
        return self.log_path

    def init_default_logger(self, verbosity=0, log_path=None, file_level=logging.DEBUG, file_fmt=None):
        """
        Initialize a logger that sends INFO messages and below to stdout and WARNING messages and above to stderr, and
        also saves all DEBUG or above logs to a file.

        :param int verbosity: Higher values increase verbosity
        :param str log_path: (optional) Path to log file destination, otherwise a default filename is used
        :param int file_level: Lowest log level to include in the file (default: DEBUG)
        :param str file_fmt: Log entry format string
        :return: Actual path that will be used for logging
        """
        self.init_default_stream_logger(verbosity)
        return self.init_default_file_logger(log_path, file_level, file_fmt)


def get_level_info(handler):
    """
    :param handler: An instance of a logging handler object
    :return: A string representation of the handler's logging level and its filters
    """
    htype = "{}.{}".format(handler.__class__.__module__, handler.__class__.__name__)
    if hasattr(handler, "stream") and hasattr(handler.stream, "name"):
        sname = handler.stream.name
        htype += sname if (sname.startswith("<") and sname.endswith(">")) else "<{}>".format(sname)
    return "{}: {} ({})".format(htype, handler.level, logging.getLevelName(handler.level))


def create_filter(filter_fn):
    """
    Uses the given function to filter log entries based on level number.  The function should return True if the
    record should be logged, or False to ignore it.

    The decompilation was mostly an exercise to see what was possible; it's obviously not necessary for the
    functionality of this class/method

    :param filter_fn: A function that takes 1 parameter (level number) and returns a boolean
    :return: A custom, initialized subclass of logging.Filter using the given filter function
    """
    class CustomLogFilter(logging.Filter):
        def filter(self, record):
            return filter_fn(record.levelno)

    return CustomLogFilter()


class DatetimeFormatter(logging.Formatter):
    def formatTime(self, record, datefmt=None):
        dt = TZ_LOCAL.localize(datetime.fromtimestamp(record.created))
        if datefmt:
            s = dt.strftime(datefmt)
        else:
            t = dt.strftime(self.default_time_format)
            s = self.default_msec_format % (t, record.msecs)
        return s


class ColorLogFormatter(DatetimeFormatter):
    def format(self, record):
        formatted = super().format(record)
        color = getattr(record, "color", None) or ("red" if getattr(record, "red", False) else None)
        if color:
            formatted = colored(formatted, color)
        if COLOR_CODED_THREADS:
            try:
                threadno = int(record.threadName.split("-")[1])
            except Exception:
                pass
            else:
                color_num = threadno % 256
                while color_num in (0, 16, 17, 18, 19, 232, 233, 234, 235, 236, 237):
                    color_num += 51
                    if color_num > 255:
                        color_num %= 256
                formatted = colored(formatted, color_num)
        return formatted


def create_formatter(should_format_fn, format_fn):
    """
    Example usage of an extra attribute: ``log.error("Example message", extra={"red": True})``

    :param should_format_fn: fn(record) that returns True for the format to be applied, False otherwise
    :param format_fn: fn(message) that returns the formatted message
    :return: A custom, uninitialized subclass of logging.Formatter
    """
    class CustomLogFormatter(DatetimeFormatter):
        def format(self, record):
            formatted = super(CustomLogFormatter, self).format(record)
            if should_format_fn(record):
                formatted = format_fn(formatted)
            return formatted

    return CustomLogFormatter


def prep_log_dir(log_path, perm_change_prefix="/var/tmp/", new_dir_permissions=0o1777):
    """
    Creates any necessary intermediate directories in order for the given log path to be valid.  Log directory's
    permissions default to 1777 (sticky, read/write/exec for everyone).

    :param str log_path: Log file destination
    :param str perm_change_prefix: Apply new_dir_permissions to the dir if it needs to be created and starts with this
    :param new_dir_permissions: Octal permissions for the new directory if it needs to be created.
    """
    log_dir = os.path.dirname(log_path)
    validate_or_make_dir(log_dir, permissions=new_dir_permissions if log_dir.startswith(perm_change_prefix) else None)


def add_context_filter(filter_instance, name=None):
    """
    :param filter_instance: An instance of the :class:`logging.Filter` class that should be used
    :param str|None name: None to add to all loggers, or a string that is the prefix of all loggers that should use the
      given filter
    """
    for lname, logger in logging.Logger.manager.loggerDict.items():
        if (name is None) or (isinstance(lname, str) and lname.startswith(name)):
            try:
                logger.addFilter(filter_instance)
            except AttributeError:                  # ignore PlaceHolder objects
                pass


if __name__ == "__main__":
    lm = LogManager.create_default_logger(
        2, log_path=None, date_fmt="%Y-%m-%d %H:%M:$S.%f %Z", entry_fmt="%(asctime)s %(name)s %(message)s"
    )
