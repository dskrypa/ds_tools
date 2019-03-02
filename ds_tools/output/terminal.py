"""
Functions for printing unicode data to stdout/stderr, and for determining the height/width of both Linux and Windows
terminals.

:author: Doug Skrypa
"""

import logging
import os
import struct
import sys
from collections import Callable

if sys.platform == 'win32':
    from ctypes import windll, create_string_buffer
else:
    try:
        from fcntl import ioctl
        from termios import TIOCGWINSZ
    except ImportError:
        pass

__all__ = ['Terminal', 'uprint', 'uerror']
log = logging.getLogger(__name__)

try:
    _uout = open(sys.stdout.fileno(), mode='w', encoding='utf-8', buffering=1)
    _uerr = open(sys.stderr.fileno(), mode='w', encoding='utf-8', buffering=1)
except Exception:
    _uout = sys.stdout
    _uerr = sys.stderr


def uprint(msg):
    _uout.write(msg + "\n")
    _uout.flush()


def uerror(msg):
    _uerr.write(msg + "\n")
    _uerr.flush()


class Terminal:
    def __init__(self):
        stdout = sys.__stdout__
        self._fd = stdout.fileno() if hasattr(stdout, 'fileno') and isinstance(stdout.fileno, Callable) else None

    def _height_and_width(self):
        """
        Windows method based on: http://code.activestate.com/recipes/440694/

        Linux method based on: `blessings.Terminal <https://pypi.org/project/blessings/>`_

        :return tuple: The (height, width) of the terminal as integers representing the number of characters that can
          fit in each direction; defaults to (40, 160) if no accurate method could be used to measure the dimensions
        """
        if sys.platform == 'win32':
            h = windll.kernel32.GetStdHandle(-12)
            csbi = create_string_buffer(22)
            res = windll.kernel32.GetConsoleScreenBufferInfo(h, csbi)
            if not res:
                return 40, 160

            bufx, bufy, curx, cury, wattr, left, top, right, bottom, maxx, maxy = struct.unpack('hhhhHhhhhhh', csbi.raw)
            return bottom - top + 1, right - left + 1
        else:
            for descriptor in self._fd, sys.__stdout__:
                try:
                    return struct.unpack('hhhh', ioctl(descriptor, TIOCGWINSZ, '\000' * 8))[0:2]
                except Exception:
                    pass

        try:
            return int(os.environ.get('LINES')), int(os.environ.get('COLUMNS'))
        except TypeError:
            return 40, 160

    @property
    def height(self):
        return self._height_and_width()[0]

    @property
    def width(self):
        return self._height_and_width()[1]
