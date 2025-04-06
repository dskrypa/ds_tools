"""
Library for communicating with monitors via DDC (Display Data Channel)

:author: Doug Skrypa
"""

import sys

if sys.platform == 'win32':
    from ._windows.vcp import WindowsVCP as PlatformVcp
elif sys.platform.startswith('linux'):
    from ._linux.vcp import LinuxVCP as PlatformVcp

from .exceptions import VCPError
