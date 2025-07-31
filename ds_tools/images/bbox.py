from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import TYPE_CHECKING, Iterable

from numpy import unique, uint32, array, asarray
from PIL.Image import open as open_image

from .geometry import Box

if TYPE_CHECKING:
    from numpy.typing import NDArray

__all__ = ['Image', 'ImageInfo']
log = logging.getLogger(__name__)


class Image:
    _pack_arrays = {
        1: array([1], dtype=uint32),
        2: array([1, 256], dtype=uint32),
        3: array([1, 256, 65536], dtype=uint32),
        4: array([1, 256, 65536, 16777216], dtype=uint32),  # 2 ** (0, 8, 16, 24)
    }

    def __init__(self, path: Path | str):
        self.path = Path(path).expanduser()
        self.data = asarray(open_image(self.path))
        # Note: imageio.imiter(self.path) can be used to iterate over individual frames as numpy arrays
        height, width, self.bands = self.data.shape
        self.box = Box.from_size_and_pos(width, height)

    # def crop_to_bbox(self):
    #     return open_image(self.path).crop(self.find_bbox().as_bbox())

    @cached_property
    def _transposed(self) -> NDArray:
        return self.data.transpose(1, 0, 2)

    def get_info(self, threshold: float = 0.99) -> ImageInfo:
        return ImageInfo(self.path, box=self.box, bbox=self.find_bbox(threshold), bands=self.bands)

    def find_bbox(self, threshold: float = 0.99) -> Box:
        # return Box(0, self.find_top(threshold), self.box.right, self.find_bottom(threshold))
        return Box(self.find_left(), self.find_top(threshold), self.find_right(), self.find_bottom(threshold))

    def find_top(self, threshold: float = 0.99) -> int:
        return self._find_row(self.data, threshold)

    def find_bottom(self, threshold: float = 0.99) -> int:
        return self.box.bottom - self._find_row(self.data[::-1], threshold)

    def find_left(self, threshold: float = 0.99) -> int:
        return self._find_row(self._transposed, threshold)

    def find_right(self, threshold: float = 0.99) -> int:
        return self.box.right - self._find_row(self._transposed[::-1], threshold)

    def _find_row(self, image_data: NDArray, threshold: float = 0.99) -> int:
        pack_array = self._pack_arrays[image_data.shape[2]]
        row: NDArray
        # TODO: There's a much better way to do identify the bbox using numpy
        for i, row in enumerate(image_data):
            # Pack each pixel's 3-4 RGB(A) 8-bit ints into a 32-bit int so that counting unique values counts full
            # colors instead of counting unique values for individual bands
            row = row.dot(pack_array)
            values, counts = unique(row, return_counts=True)
            if len(values) == 1:  # Only one unique value
                continue
            if (counts.max() / len(row)) < threshold:
                return i
        return 0


@dataclass
class ImageInfo:
    path: Path
    box: Box
    bbox: Box
    bands: int

    @cached_property
    def seconds(self) -> int:
        return int(self.path.stem.rsplit('_', 1)[-1]) - 1  # ffmpeg starts from 1

    def find_closest_bbox(self, boxes: Iterable[Box]) -> Box:
        return min(boxes, key=lambda box: abs(box.area - self.bbox.area))

    def __lt__(self, other: ImageInfo) -> bool:
        return self.seconds < other.seconds
