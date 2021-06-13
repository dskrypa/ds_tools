"""
Functions for printing unicode data to stdout/stderr

:author: Doug Skrypa
"""

import sys

__all__ = ['uprint']


def uprint(msg):
    try:
        stdout = uprint._stdout
    except AttributeError:
        if sys.stdout.encoding.lower().startswith('utf'):
            uprint._stdout = stdout = sys.stdout
        else:
            uprint._stdout = stdout = open(sys.stdout.fileno(), mode='w', encoding='utf-8', buffering=1)

    if isinstance(msg, bytes):
        msg = msg.decode('utf-8')
    else:
        msg = msg if isinstance(msg, str) else str(msg)
    stdout.write(msg + '\n')
    stdout.flush()
