from pathlib import Path
from typing import Union, Iterable

PathLike = Union[str, Path]
Paths = Union[PathLike, Iterable[PathLike]]
