from __future__ import annotations

from abc import abstractmethod
from pathlib import Path
from typing import Iterable, Protocol, runtime_checkable

from PIL.Image import Image as PILImage


ImageType = PILImage | bytes | Path | str | None
ImageTypeIter = Iterable[ImageType]

XY = tuple[int, int]
OptXY = tuple[int | None, int | None]
OptXYF = tuple[float | None, float | None]

Size = tuple[int, int]
IntBox = tuple[int, int, int, int]
FloatBox = tuple[float, float, float, float]

RGB = tuple[int, int, int]
RGBA = tuple[int, int, int, int]
Color = str | RGB | RGBA


@runtime_checkable
class HasSize(Protocol):
    __slots__ = ()

    @property
    @abstractmethod
    def size(self) -> XY:
        pass
