from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import TYPE_CHECKING, Iterable

from .array import ImageArray
from .geometry import Box
from .utils import as_image, get_image_path

if TYPE_CHECKING:
    from .typing import ImageType

__all__ = ['ImageInfo']
log = logging.getLogger(__name__)


@dataclass
class ImageInfo:
    path: Path | None
    box: Box
    bbox: Box
    bands: int

    @classmethod
    def for_image(cls, image: ImageType) -> ImageInfo:
        path = get_image_path(image)
        ia = ImageArray(as_image(image))
        height, width, bands = ia.arr.shape
        return cls(path, box=Box.from_size_and_pos(width, height), bbox=ia.find_bbox(), bands=bands)

    @cached_property
    def seconds(self) -> int:
        return int(self.path.stem.rsplit('_', 1)[-1]) - 1  # ffmpeg starts from 1

    def find_closest_bbox(self, boxes: Iterable[Box]) -> Box:
        return min(boxes, key=lambda box: abs(box.area - self.bbox.area))

    def __lt__(self, other: ImageInfo) -> bool:
        return self.seconds < other.seconds
