#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
:author: Doug Skrypa
"""

import time
from datetime import datetime

import pytz
from tzlocal import get_localzone

__all__ = [
    "TZ_LOCAL", "TZ_UTC", "ISO8601", "DATETIME_FMT", "DATE_FMT", "TIME_FMT", "now", "epoch2str", "str2epoch",
    "format_duration", "datetime_with_tz", "localize", "as_utc"
]

TZ_UTC = pytz.utc
TZ_LOCAL = get_localzone()

ISO8601 = "%Y-%m-%dT%H:%M:%SZ"
DATETIME_FMT = "%Y-%m-%d %H:%M:%S %Z"
DATETIME_FMT_NO_TZ = "%Y-%m-%d %H:%M:%S"
DATE_FMT = "%Y-%m-%d"
TIME_FMT = "%H:%M:%S %Z"
TIME_FMT_NO_TZ = "%H:%M:%S"
TZ_ALIAS_MAP = {"HKT": "Asia/Hong_Kong", "NYT": "America/New_York"}


def _get_tz(tz):
    try:
        return pytz.timezone(tz) if isinstance(tz, str) else tz or TZ_LOCAL
    except pytz.exceptions.UnknownTimeZoneError as e:
        tz_name = e.args[0]
        if tz_name in TZ_ALIAS_MAP:
            return pytz.timezone(TZ_ALIAS_MAP[tz_name])
        else:
            raise e


def datetime_with_tz(dt, fmt=DATETIME_FMT_NO_TZ, tz=None):
    """
    Converts the given timestamp string to a datetime object, and ensures that its tzinfo is set.

    :param str|float|datetime dt: A timestamp string/float or datetime object
    :param str fmt: Time format used by the given input string
    :param tz: A :class:`datetime.tzinfo` or str timezone name to use if not parsed from dt (default: local)
    :return datetime: A :class:`datetime.datetime` object with tzinfo set
    """
    original = dt

    if isinstance(dt, str):
        dt = datetime.strptime(dt, fmt)
    elif isinstance(dt, (int, float)):
        dt = datetime.fromtimestamp(dt)

    if not dt.tzinfo:
        # datetime.strptime discards TZ
        if tz is not None:
            tz = _get_tz(tz)
        else:
            try:
                tz = _get_tz(time.strptime("%Z", time.strptime(original, fmt)))
            except Exception:
                tz = _get_tz(None)
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
