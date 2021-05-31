"""
Utilities for working with animated gif images

:author: Doug Skrypa
"""

from pathlib import Path
from typing import Union


def prepare_dir(path: Union[Path, str]) -> Path:
    path = Path(path).expanduser().resolve() if isinstance(path, str) else path
    if path.exists():
        if not path.is_dir():
            raise ValueError(f'Invalid path={path.as_posix()!r} - it must be a directory')
    else:
        path.mkdir(parents=True)
    return path
