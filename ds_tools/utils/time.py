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
    "format_duration"
]

TZ_UTC = pytz.utc
TZ_LOCAL = get_localzone()

ISO8601 = "%Y-%m-%dT%H:%M:%SZ"
DATETIME_FMT = "%Y-%m-%d %H:%M:%S %Z"
DATE_FMT = "%Y-%m-%d"
TIME_FMT = "%H:%M:%S %Z"


def now(fmt=DATETIME_FMT, tz=None):
    """
    Returns the current time in the given format, optionally converted to the given timezone.

    :param str fmt: The time format to use
    :param tz: A pytz.timezone or str timezone name (default: local)
    :return str: Current time in the requested format
    """
    tz = pytz.timezone(tz) if isinstance(tz, str) else tz or TZ_LOCAL
    dt = TZ_LOCAL.localize(datetime.now())
    if tz != TZ_LOCAL:
        return dt.astimezone(tz).strftime(fmt)
    return dt.strftime(fmt)


def epoch2str(epoch_ts, fmt=DATETIME_FMT, millis=False, tz=None):
    """
    Returns the given POSIX timestamp as a string with the given format, optionally converted to the given timezone

    :param float epoch_ts: Seconds or milliseconds since the Unix epoch
    :param str fmt: Time format to use for output
    :param bool millis: The provided timestamp was in milliseconds instead of seconds (default: False)
    :param tz: A pytz.timezone or str timezone name (default: local)
    :return str: The given time in the given format
    """
    tz = pytz.timezone(tz) if isinstance(tz, str) else tz or TZ_LOCAL
    dt = datetime.fromtimestamp((epoch_ts // 1000) if millis else epoch_ts)
    return tz.localize(dt).strftime(fmt)


def str2epoch(datetime_str, fmt=DATETIME_FMT, millis=False, tz=None):
    """
    Convert a string timestamp to a POSIX timestamp (seconds/milliseconds since the Unix epoch of 1970-01-01T00:00:00Z)

    :param str datetime_str: A timestamp string
    :param str fmt: Time format used by the given input string
    :param bool millis: Return milliseconds since epoch instead of seconds
    :param tz: A pytz.timezone or str timezone name (default: from timestamp if available, otherwise local)
    :return int: The seconds or milliseconds since epoch that corresponds with the given timestamp
    """
    if tz is not None:
        tz = pytz.timezone(tz) if isinstance(tz, str) else tz
    else:
        tz_name = time.strftime("%Z", time.strptime(datetime_str, fmt))     # datetime.strptime discards TZ
        tz = pytz.timezone(tz_name) if tz_name else TZ_LOCAL
    dt = tz.localize(datetime.strptime(datetime_str, fmt))
    return int(dt.timestamp() * 1000) // (1 if millis else 1000)


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
