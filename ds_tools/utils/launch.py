"""
Utilities for launching other applications

:author: Doug Skrypa
"""

import logging
import os
import sys
from pathlib import Path
from subprocess import Popen
from typing import Union

__all__ = ['launch', 'explore']
log = logging.getLogger(__name__)

ON_WINDOWS = sys.platform.startswith('win')
OPEN_CMD = 'xdg-open' if sys.platform.startswith('linux') else 'open'  # open is for OSX


def launch(path: Union[Path, str]):
    """Open the given path with its associated application"""
    path = Path(path)
    if ON_WINDOWS:
        os.startfile(str(path))
    else:
        Popen([OPEN_CMD, path.as_posix()])


def explore(path: Union[Path, str]):
    """Open the given path in the default file manager"""
    path = Path(path)
    if ON_WINDOWS:
        cmd = list(filter(None, ('explorer', '/select,' if path.is_file() else None, str(path))))
    else:
        cmd = [OPEN_CMD, (path if path.is_dir() else path.parent).as_posix()]

    log.debug(f'Running: {cmd}')
    Popen(cmd)
