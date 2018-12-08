#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Library to facilitate working with timezone-aware datetimes

.. note::
    If you have a :class:`datetime.datetime` object with a timezone configured, and you modify the date/time via a
    :class:`datetime.timedelta` so that the time is pushed across a DST threshold, then you will need to fix the
    timezone to reflect the new one.

    Example (with ways to fix it) - midnight on 2018-11-04 is in EDT, but 3 hours later is actually 2:00 EST::\n
        >>> pre_dst = datetime_with_tz("2018-11-04 00:00:00 America/New_York")
        >>> pre_dst.strftime(DATETIME_FMT)
        '2018-11-04 00:00:00 EDT'

        >>> post_dst = pre_dst + timedelta(hours=3)
        >>> post_dst.strftime(DATETIME_FMT)
        '2018-11-04 03:00:00 EDT'

        >>> datetime_with_tz("2018-11-04 03:00:00 America/New_York").strftime(DATETIME_FMT)
        '2018-11-04 03:00:00 EST'

        >>> datetime_with_tz(post_dst.timestamp()).strftime(DATETIME_FMT)
        '2018-11-04 02:00:00 EST'
        >>> TZ_LOCAL.normalize(post_dst).strftime(DATETIME_FMT)
        '2018-11-04 02:00:00 EST'
        >>> post_dst.astimezone(TZ_LOCAL).strftime(DATETIME_FMT)
        '2018-11-04 02:00:00 EST'

:author: Doug Skrypa
"""

import logging
import re
from datetime import datetime, timedelta
from _strptime import TimeRE                # Needed to work around timezone handling limitations

import pytz
from tzlocal import get_localzone

__all__ = [
    "TZ_LOCAL", "TZ_UTC", "ISO8601", "DATETIME_FMT", "DATE_FMT", "TIME_FMT", "now", "epoch2str", "str2epoch",
    "format_duration", "datetime_with_tz", "localize", "as_utc"
]
log = logging.getLogger("ds_tools.utils.time")
# Loggers that should not be displayed by default
logr = {"parse": logging.getLogger("ds_tools.utils.time.parse")}
for logger in logr.values():
    logger.setLevel(logging.WARNING)

TZ_UTC = pytz.utc
TZ_LOCAL = get_localzone()

ISO8601 = "%Y-%m-%dT%H:%M:%SZ"
DATETIME_FMT = "%Y-%m-%d %H:%M:%S %Z"
DATETIME_FMT_NO_TZ = "%Y-%m-%d %H:%M:%S"
DATE_FMT = "%Y-%m-%d"
TIME_FMT = "%H:%M:%S %Z"
TIME_FMT_NO_TZ = "%H:%M:%S"
TZ_ALIAS_MAP = {"HKT": "Asia/Hong_Kong", "NYT": "America/New_York"}

DT_FMT_TZ_RX = re.compile("(?<!%)%(%%)*(?!%)[zZ]")  # Odd number of preceding % => unescaped %z (i.e., need to tokenize)
time_re = TimeRE()
time_re["z"] = r"(?P<z>[+-]\d\d:?[0-5]\d)"          # Allow ':' in timezone offset notation
time_re["Z"] = r"(?P<Z>[0-9A-Za-z_/+-]+)"           # Allow any timezone possibly supported by pytz


def _get_tz(tz):
    try:
        return pytz.timezone(tz) if isinstance(tz, str) else tz or TZ_LOCAL
    except pytz.exceptions.UnknownTimeZoneError as e:
        tz_name = e.args[0]
        if tz_name in TZ_ALIAS_MAP:
            return pytz.timezone(TZ_ALIAS_MAP[tz_name])
        else:
            raise e


def _tokenize_datetime(dt, fmt):
    dt = str(dt)
    time_rx = time_re.compile(fmt)
    m = time_rx.match(dt)
    if not m:
        raise ValueError("time data {!r} does not match format {!r}".format(dt, fmt))
    if len(dt) != m.end():
        raise ValueError("unconverted data remains: {}".format(dt[m.end():]))
    return m.groupdict()


def _recompile_datetime(tokens, fmt):
    dt_str = fmt
    for token, value in tokens.items():
        dt_str = dt_str.replace("%" + token, value)
    return dt_str


def datetime_with_tz(dt, fmt=DATETIME_FMT, tz=None):
    """
    Converts the given timestamp string to a datetime object, and ensures that its tzinfo is set.

    Handles ``%z``=``[+-]\d\d:?[0-5]\d`` (Python's default strptime only supports ``[+-]\d\d[0-5]\d``)\n
    Handles long-form ``%Z`` values provided in ``dt`` (e.g., ``America/New_York``)

    :param str|float|datetime dt: A timestamp string/float or datetime object
    :param str fmt: Time format used by the given input string
    :param tz: A :class:`datetime.tzinfo` or str timezone name to use if not parsed from dt (or instead of the one that
      is in dt if dt is a string) (default: local)
    :return datetime: A :class:`datetime.datetime` object with tzinfo set
    """
    _log = logr["parse"]
    original_dt = dt
    # original_fmt = fmt
    tokens = {}
    if isinstance(dt, str):
        if DT_FMT_TZ_RX.search(fmt):                # Trade-off: %z without : won't need this, but more conditions
            tokens = _tokenize_datetime(dt, fmt)    # would be required to tell if tokens should be generated later
            if tz:
                fmt = fmt.replace("%z", "").replace("%Z", "")
                dt = _recompile_datetime(tokens, fmt)           # type(dt) is still str here
                for tok in ("z", "Z"):
                    if tok in tokens:
                        dbg_fmt = "Discarding %{}='{}' from '{}' due to provided tz={!r}"
                        _log.debug(dbg_fmt.format(tok, tokens[tok], original_dt, tz))

        try:
            dt = datetime.strptime(dt, fmt)
        except ValueError as e:
            if tokens and "does not match format" in str(e):
                if ("z" in tokens) and (":" in tokens["z"]):
                    tokens["z"] = tokens["z"].replace(":", "")
                    dt = datetime.strptime(_recompile_datetime(tokens, fmt), fmt)
                elif "Z" in tokens:
                    alt_fmt = fmt.replace("%Z", "")
                    dt = datetime.strptime(_recompile_datetime(tokens, alt_fmt), alt_fmt)
                else:
                    raise e
            else:
                raise e
    elif isinstance(dt, (int, float)):
        dt = datetime.fromtimestamp(dt)

    # From this point forward, type(dt) is (assumed to be) datetime - it will no longer be str or a number
    if not dt.tzinfo:
        if tz is not None:
            tz = _get_tz(tz)
        else:
            if tokens.get("Z"):             # datetime.strptime discards TZ when provided via %Z but retains it via %z
                tz = _get_tz(tokens["Z"])
                _log.debug("Found tz={!r} => {!r} for datetime: {!r}".format(tokens["Z"], tz, original_dt))
            else:
                _log.debug("Defaulting to tz={!r} for datetime without %Z or %z: {!r}".format(TZ_LOCAL, original_dt))
                tz = TZ_LOCAL
        dt = tz.localize(dt)
    return dt


def now(fmt=DATETIME_FMT, tz=None, as_datetime=False):
    """
    Returns the current time in the given format, optionally converted to the given timezone.

    :param str fmt: The time format to use
    :param tz: A :class:`datetime.tzinfo` or str timezone name (default: local)
    :param bool as_datetime: If True, return a :class:`datetime.datetime` object instead of a formatted string
    :return str: Current time in the requested format
    """
    tz = _get_tz(tz)
    dt = TZ_LOCAL.localize(datetime.now())
    if tz != TZ_LOCAL:
        dt = dt.astimezone(tz)
    return dt if as_datetime else dt.strftime(fmt)


def epoch2str(epoch_ts, fmt=DATETIME_FMT, millis=False, tz=None):
    """
    Returns the given POSIX timestamp as a string with the given format, optionally converted to the given timezone

    :param float epoch_ts: Seconds or milliseconds since the Unix epoch
    :param str fmt: Time format to use for output
    :param bool millis: The provided timestamp was in milliseconds instead of seconds (default: False)
    :param tz: A :class:`datetime.tzinfo` or str timezone name (default: local)
    :return str: The given time in the given format
    """
    tz = _get_tz(tz)
    dt = datetime.fromtimestamp((epoch_ts // 1000) if millis else epoch_ts)
    return tz.localize(dt).strftime(fmt)


def str2epoch(dt, fmt=DATETIME_FMT_NO_TZ, millis=False, tz=None):
    """
    Convert a string timestamp to a POSIX timestamp (seconds/milliseconds since the Unix epoch of 1970-01-01T00:00:00Z)

    :param str|float|datetime dt: A timestamp string/float/int or datetime object
    :param str fmt: Time format used by the given input string
    :param bool millis: Return milliseconds since epoch instead of seconds
    :param tz: A :class:`datetime.tzinfo` or str timezone name (default: from timestamp if available, otherwise local)
    :return int: The seconds or milliseconds since epoch that corresponds with the given timestamp
    """
    dt = datetime_with_tz(dt, fmt, tz)
    return int(dt.timestamp() * 1000) // (1 if millis else 1000)


def localize(dt, in_fmt=DATETIME_FMT_NO_TZ, out_fmt=DATETIME_FMT, in_tz=None, out_tz=None):
    """
    Convert the given timestamp string from one timezone to another

    :param str|float|datetime dt: A timestamp string/float or datetime object
    :param str in_fmt: Time format used by the given input string
    :param str out_fmt: Time format to use for output
    :param in_tz: A :class:`datetime.tzinfo` or str timezone name to use if not parsed from dt (default: local)
    :param out_tz: The :class:`datetime.tzinfo` or str timezone name to use for output (default: local)
    :return str: The given time in the given timezone and format
    """
    dt = datetime_with_tz(dt, in_fmt, in_tz)
    return dt.astimezone(_get_tz(out_tz)).strftime(out_fmt)


def as_utc(dt, in_fmt=DATETIME_FMT_NO_TZ, out_fmt=DATETIME_FMT, tz=None):
    """

    :param str|float|datetime dt: A timestamp string/float or datetime object
    :param str in_fmt: Time format used by the given input string
    :param str out_fmt: Time format to use for output
    :param tz: A :class:`datetime.tzinfo` or str timezone name to use if not parsed from dt (default: local)
    :return str: The given time in UTC in the given format
    """
    return localize(dt, in_fmt=in_fmt, out_fmt=out_fmt, in_tz=tz, out_tz=TZ_UTC)


def format_duration(seconds):
    """
    Formats time in seconds as (Dd)HH:MM:SS (timt.stfrtime() is not useful for formatting durations).

    :param int seconds: Number of seconds to format
    :return: Given number of seconds as (Dd)HH:MM:SS
    """
    x = "-" if seconds < 0 else ""
    m, s = divmod(abs(seconds), 60)
    h, m = divmod(m, 60)
    d, h = divmod(h, 24)
    x = "{}{}d".format(x, d) if d > 0 else x
    return "{}{:02d}:{:02d}:{:02d}".format(x, h, m, s)


def timedelta_to_str(delta):
    m, s = divmod(delta.seconds, 60)
    h, m = divmod(m, 60)
    td_str = "{:d}:{:02d}:{:02d}".format(h, m, s)
    if delta.days != 0:
        td_str = "{:d}d, {}".format(delta.days, td_str)
    return td_str


if __name__ == "__main__":
    from ds_tools.logging import LogManager
    lm = LogManager.create_default_logger(2, log_path=None, levels={"ds_tools.utils.time.parse": "DEBUG"})

