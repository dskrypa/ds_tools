from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Iterator, Type, Collection

from numpy import array, asarray, nonzero, full as np_full
from PIL.Image import Resampling, Image as PILImage
from PIL.ImageFilter import GaussianBlur, MedianFilter

from .multi import MultiHash, HT

if TYPE_CHECKING:
    from numpy.typing import NDArray

__all__ = ['CropResistantMultiHash']
log = logging.getLogger(__name__)

Pixel = tuple[int, int]
ANTIALIAS = Resampling.LANCZOS


class CropResistantMultiHash(MultiHash, mode='crop_resistant'):
    """
    Based heavily on the ``ImageMultiHash`` class and ``crop_resistant_hash`` function in ``imagehash``, with a few
    optimizations around segmentation.

    Approximately 3x slower than :class:`RotatedMultiHash`.
    """
    __slots__ = ()

    @classmethod
    def from_image(
        cls,
        image: PILImage,
        hash_cls: Type[HT],
        *,
        segment_limit: int = None,
        segment_threshold: int = 128,
        min_segment_size: int = 500,
        pre_segment_size: int = 300,
    ) -> CropResistantMultiHash[HT]:
        gray_img = image.convert('L')  # Note: original used the original image in most places where this is used
        # Using the pre-resized image did not provide a significant perf boost for this
        # gray_img = image.convert('L').resize((pre_segment_size, pre_segment_size), ANTIALIAS)

        segments = Segment.find_all(
            asarray(
                gray_img.resize((pre_segment_size, pre_segment_size), ANTIALIAS) \
                    .filter(GaussianBlur()).filter(MedianFilter())
            ),
            # asarray(gray_img.filter(GaussianBlur()).filter(MedianFilter())),
            segment_threshold,
            min_segment_size,
        )
        if segment_limit:                       # If segment limit is set, discard the smaller segments
            segments = sorted(segments, reverse=True)[:segment_limit]

        # Create bounding box for each segment
        orig_w, orig_h = gray_img.size
        scale_w = orig_w / pre_segment_size
        scale_h = orig_h / pre_segment_size
        # scale_w = scale_h = 1

        # boxes = '\n'.join(f'  - {seg.bbox(scale_w, scale_h)}' for seg in segments)
        # log.debug(f'Using {len(segments)} segments:\n{boxes}')
        return cls([hash_cls.from_image(gray_img.crop(seg.bbox(scale_w, scale_h)), skip_prep=True) for seg in segments])

    # region Comparison Methods

    def difference(
        self, other: CropResistantMultiHash[HT], max_distance: float = None, bit_error_rate: float = None
    ) -> float:
        if distances := self._distances(other, max_distance, bit_error_rate):
            matches = len(distances)
            max_distance = matches * len(self.hashes[0])
            match_score = matches - (sum(distances) / max_distance)  # matches - tie_breaker
            return len(self.hashes) - match_score
        else:
            return len(self.hashes)  # max_difference

    __sub__ = difference

    def relative_difference(
        self, other: CropResistantMultiHash[HT], max_distance: float = None, bit_error_rate: float = None
    ) -> float:
        # Closer to 0 means fewer differences, closer to 1 means more differences
        return self.difference(other, max_distance, bit_error_rate) / len(self.hashes)

    __or__ = relative_difference

    def matches(
        self,
        other: CropResistantMultiHash[HT],
        min_regions: int = 1,
        max_distance: float = None,
        bit_error_rate: float = None,
    ) -> bool:
        """
        Checks whether this hash matches another crop resistant hash, ``other``.

        :param other: The image multi hash to compare against
        :param min_regions: The minimum number of regions which must have a matching hash
        :param max_distance: The maximum hamming distance to a region hash in the target hash
        :param bit_error_rate: Percentage of bits which can be incorrect, an alternative to the hamming cutoff. The
          default of 0.25 means that the segment hashes can be up to 25% different
        """
        return len(self._distances(other, max_distance, bit_error_rate)) > min_regions

    def _distances(
        self, other: CropResistantMultiHash[HT], max_distance: float = None, bit_error_rate: float = None
    ) -> list[int]:
        """
        Gets the difference between two multi-hashes, as a tuple. The first element of the tuple is the number of
        matching segments, and the second element is the sum of the hamming distances of matching hashes.
        NOTE: Do not order directly by this tuple, as higher is better for matches, and worse for hamming cutoff.

        :param other: The image multi hash to compare against
        :param max_distance: The maximum hamming distance to a region hash in the target hash
        :param bit_error_rate: Percentage of bits which can be incorrect, an alternative to the hamming cutoff. The
          default of 0.25 means that the segment hashes can be up to 25% different
        """
        if max_distance is None:
            max_distance = len(self.hashes[0]) * (0.25 if bit_error_rate is None else bit_error_rate)
        # Get the hash distance for each region hash within cutoff
        return [
            lowest_dist
            for seg_hash in self.hashes
            if (lowest_dist := min(seg_hash - other_seg_hash for other_seg_hash in other.hashes)) <= max_distance
        ]

    def rank_similarity(
        self, others: Collection[CropResistantMultiHash[HT]], max_distance: float = None, bit_error_rate: float = None
    ) -> list[tuple[float, CropResistantMultiHash[HT]]]:
        return sorted(((self.difference(other, max_distance, bit_error_rate), other) for other in others))

    # endregion


class Segment:
    __slots__ = ('x_coords', 'y_coords', 'size')

    def __init__(self, pixels: NDArray):
        self.x_coords = pixels[:, 0]
        self.y_coords = pixels[:, 1]
        self.size = len(pixels)

    @classmethod
    def find_region(cls, remaining_pixels, segmented: set[Pixel]) -> Segment:
        """
        Finds a region and returns a set of pixel coordinates for it.

        :param remaining_pixels: A numpy bool array, with True meaning the pixels are remaining to segment
        :param segmented: A set of pixel coordinates which have already been assigned to segment. This will be
          updated with the new pixels added to the returned segment.
        """
        # Note: The following is slightly faster than `tuple(transpose(nonzero(remaining_pixels))[0])`
        y_coords, x_coords = nonzero(remaining_pixels)  # noqa
        start: Pixel = (y_coords[0], x_coords[0])  # noqa
        not_in_region = set()
        in_region = [start]
        new = {start}
        # y, x here is more accurate than x, y since the first dimension is height
        while try_next := (
            {p for y, x in new for p in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1))} - segmented - not_in_region
        ):
            # Empty new pixels set, so we know whose neighbors to check next time
            new = {pixel for pixel in try_next if remaining_pixels[pixel]}
            in_region.extend(new)
            segmented.update(new)
            not_in_region.update(try_next - new)

        return cls(array(in_region))

    @classmethod
    def find_all(cls, pixels: NDArray, segment_threshold: int = 128, min_segment_size: int = 500) -> list[Segment]:
        if segments := list(cls._find_all(pixels, segment_threshold, min_segment_size)):
            return segments
        else:  # [this is unlikely] If there are no segments, have 1 segment including the whole image
            return [Segment(array([0, 0], (pixels.shape[0] - 1, pixels.shape[1] - 1)))]

    @classmethod
    def _find_all(cls, pixels: NDArray, segment_threshold: int = 128, min_segment_size: int = 500) -> Iterator[Segment]:
        # Note: numpy image arrays have shape (height, width), which differs from the (width, height) order used for
        # most image-related `size` attributes.
        img_height, img_width = pixels.shape
        threshold_pixels = pixels > segment_threshold
        unassigned_pixels = np_full(pixels.shape, True, dtype=bool)

        # Add all the pixels around the border outside the image:
        already_segmented = {(x, z) for x in (-1, img_width) for z in range(img_height)}
        already_segmented.update((z, y) for y in (-1, img_height) for z in range(img_width))

        # Find all the "hill" regions
        while (remaining_pixels := threshold_pixels & unassigned_pixels).any():
            segment = cls.find_region(remaining_pixels, already_segmented)
            unassigned_pixels[segment.x_coords, segment.y_coords] = False
            if segment.size > min_segment_size:
                yield segment

        # Invert the threshold matrix, and find "valleys"
        threshold_pixels_i = ~threshold_pixels
        img_area = img_width * img_height
        while len(already_segmented) < img_area:
            segment = cls.find_region(threshold_pixels_i & unassigned_pixels, already_segmented)
            unassigned_pixels[segment.x_coords, segment.y_coords] = False
            if segment.size > min_segment_size:
                yield segment

    def bbox(self, scale_w: float, scale_h: float) -> tuple[float, float, float, float]:
        return (
            self.x_coords.min() * scale_w,  # min_x
            self.y_coords.min() * scale_h,  # min_y
            (self.x_coords.max() + 1) * scale_w,  # max_x
            (self.y_coords.max() + 1) * scale_h,  # max_y
        )

    def __eq__(self, other: Segment) -> bool:
        return self.size == other.size and self.x_coords == other.x_coords and self.y_coords == other.y_coords

    def __lt__(self, other: Segment) -> bool:
        return self.size < other.size
