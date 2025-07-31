from __future__ import annotations

from abc import abstractmethod
from pathlib import Path
from typing import Annotated, Iterable, Protocol, runtime_checkable

from numpy import uint8
from numpy.typing import NDArray
from PIL.Image import Image as PILImage


ImageType = PILImage | bytes | Path | str | None
ImageTypeIter = Iterable[ImageType]

XY = tuple[int, int]
XYF = tuple[float | int, float | int]
OptXY = tuple[int | None, int | None]
OptXYF = tuple[float | int | None, float | int | None]

Size = tuple[int, int]
IntBox = tuple[int, int, int, int]
FloatBox = tuple[float, float, float, float]

RGB = tuple[int, int, int]
RGBA = tuple[int, int, int, int]
Color = str | RGB | RGBA

NP_RGB = Annotated[NDArray[uint8], (3,)]
NP_RGBA = Annotated[NDArray[uint8], (4,)]
NP_Gray = Annotated[NDArray[uint8], (1,)]
NP_Image = NP_RGB | NP_RGBA | NP_Gray


@runtime_checkable
class HasSize(Protocol):
    __slots__ = ()

    @property
    @abstractmethod
    def size(self) -> XY:
        pass
