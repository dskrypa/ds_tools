from __future__ import annotations

from abc import abstractmethod
from pathlib import Path
from typing import Annotated, Iterable, Literal, Protocol, runtime_checkable

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

# Annotated usage below is based on https://stackoverflow.com/a/72585748/19070573
NP_RGB = Annotated[NDArray[uint8], Literal[3]]
NP_RGBA = Annotated[NDArray[uint8], Literal[4]]
NP_Gray = Annotated[NDArray[uint8], Literal[1]]
NP_Pixel = NP_RGB | NP_RGBA | NP_Gray

PixelColor = Color | int | NP_Pixel

NPI_RGB = Annotated[NDArray[uint8], Literal['N', 'N', 3]]
NPI_RGBA = Annotated[NDArray[uint8], Literal['N', 'N', 4]]
NPI_Gray = Annotated[NDArray[uint8], Literal['N', 'N', 1]]
NP_Image = NPI_RGB | NPI_RGBA | NPI_Gray


@runtime_checkable
class HasSize(Protocol):
    __slots__ = ()

    @property
    @abstractmethod
    def size(self) -> XY:
        pass
