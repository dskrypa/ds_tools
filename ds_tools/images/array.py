from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from numpy import any as np_any, asarray, array, unique, argmax, argmin

from .colors import normalize_pixel_color
from .geometry import Box

if TYPE_CHECKING:
    from PIL.Image import Image as PILImage
    from .typing import NP_Image, NP_Pixel, PixelColor

__all__ = ['ImageArray']
log = logging.getLogger(__name__)


class ImageArray:
    __slots__ = ('arr',)
    arr: NP_Image

    def __init__(self, image: PILImage):
        self.arr = asarray(image)  # shape: (height, width, channels)

    def find_bbox(self, border_color: PixelColor | None = None) -> Box:
        if border_color is None:
            border_color = self.find_border_color()
        else:
            border_color = normalize_pixel_color(border_color)

        mask = np_any(self.arr != border_color, axis=-1)  # shape: (H, W), True where content differs
        rows = np_any(mask, axis=1).nonzero()[0]  # shape: (H,)
        cols = np_any(mask, axis=0).nonzero()[0]  # shape: (W,)
        # rows / cols are 1D arrays of the indexes of pixels that differ from the specified/discovered border color.
        # While this approach correctly identifies the top/left indices, it seems to have an off-by-one error for
        # bottom/right, so they are increased by 1 below...
        top, bottom = (int(rows[0]), int(rows[-1]) + 1) if rows.size else (0, self.arr.shape[0])
        left, right = (int(cols[0]), int(cols[-1]) + 1) if cols.size else (0, self.arr.shape[1])
        return Box(left, top, right, bottom)

    def find_border_color(self) -> NP_Pixel:
        """
        Examine the pixel from each of this image's four corners to determine which one is most likely to match the
        rest of the border around the real content, which is assumed to be in the center of the image.
        :returns: A numpy array
        """
        # This indexing syntax results in an array containing cells [0, 0], [0, -1], [-1, 0], and [-1, -1]
        corners = self.arr[[0, 0, -1, -1], [0, -1, 0, -1]]  # shape: (4, channels[3 or 4; 1 if grayscale])
        # While self.arr is a 3D array where index (y*, x) -> pixel (R, G, B[, A]), corners is a 2D array.
        # In some ways, it is easier to conceptualize self.arr and corners as 2D and 1D arrays of pixels, respectively.
        # Indexing to target the alpha channel for self.arr should target axis=2 (3rd), and axis=1 (2nd) for corners.
        # *: y is the first axis because the shape is (height, width, channels)

        if self.arr.shape[2] == 4:  # It has an alpha channel
            # Transparent colors around the edges are most likely the ones that should be cropped, so filter to those
            # if they are present
            transparent = corners[corners[:, -1] == 0]  # Filters the contents of corners to rows where the last val==0
            if transparent.size == 1:
                return transparent[0]
            elif transparent.size:
                corners = transparent

        values, counts = unique(corners, return_counts=True, axis=0)  # Finds unique RGB(A) values
        # Note: values/counts match such that counts[N] is the count of occurrences of values[N]
        if values.size == 1:  # All values were the same
            return values[0]
        elif counts.size == corners.size:
            # All values are unique, so in theory, the darkest is most likely to be the border color
            # Calculate luma (Y') to determine lightness; see: https://en.wikipedia.org/wiki/Rec._709#Luma_coefficients
            weights = array([0.2126, 0.7152, 0.0722])
            # The array passed to `argmin` is similar to `[rgb_to_hls(*rgb)[1] for rgb in corners[:,:3] / 255]`
            return corners[argmin((corners[:,:3] / 255) @ weights)]
        else:
            # At least one color occurred multiple times - use the one that occurred most frequently
            # Note: argmin/argmax returns the index of the element that is the min/max within the given array.
            return values[argmax(counts)]
