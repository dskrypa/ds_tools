from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from functools import cached_property
from math import log2
from typing import TYPE_CHECKING, Annotated, Collection, Literal, Type

from numpy import asarray, frombuffer, packbits, unpackbits, count_nonzero, median, uint8
from numpy.typing import NDArray
from PIL import ImageFile
from PIL.Image import Resampling, Image as PILImage

try:
    from pywt import wavedec2, waverec2
except ImportError:
    wavedec2 = waverec2 = None

from ..utils import as_image

if TYPE_CHECKING:
    from ..typing import ImageType

__all__ = [
    'ImageHashBase', 'HorizontalDifferenceHash', 'VerticalDifferenceHash', 'DifferenceHash', 'WaveletHash',
    'HASH_MODES', 'get_hash_class',
]
log = logging.getLogger(__name__)

ANTIALIAS = Resampling.LANCZOS
NEAREST = Resampling.NEAREST

ImageFile.LOAD_TRUNCATED_IMAGES = True  # Allow truncated images to be processed without error

HASH_MODES: dict[str, Type[ImageHashBase]] = {}


class ImageHashBase(ABC):
    """
    A 64-bit hash of an image.  Based heavily on the implementation in
    `imagehash<https://github.com/JohannesBuchner/imagehash>`__, but with some differences / optimizations for
    this use case.  Most notably, the hash array is stored as / expected to be a 1x8 array of uint8 values
    instead of an 8x8 array of bools.
    """
    array: Annotated[NDArray[uint8], Literal[8]]  # A 1D array with 8x uint8 values
    mode: str
    _hash_x_offset: int = 0
    _hash_y_offset: int = 0

    def __init_subclass__(
        cls, mode: str, aliases: Collection[str] = (), hash_x_offset: int = 0, hash_y_offset: int = 0, **kwargs
    ):
        super().__init_subclass__(**kwargs)
        for alias in aliases:
            HASH_MODES[alias] = cls
        HASH_MODES[mode] = cls
        cls.mode = mode
        if hash_x_offset:
            cls._hash_x_offset = hash_x_offset
        if hash_y_offset:
            cls._hash_y_offset = hash_y_offset

    # region Init

    def __init__(self, hash_array: NDArray[uint8]):
        """
        :param hash_array: A 1x8 numpy array of uint8 values.  If you have an array of bools or 1/0s, use
          ``numpy.packbits`` on it to obtain the value expected here.
        """
        self.array = hash_array

    @classmethod
    @abstractmethod
    def from_image(cls, image: PILImage, hash_size: int = 8, skip_prep: bool = False):
        raise NotImplementedError

    @classmethod
    def from_any(cls, image: ImageType | str, hash_size: int = 8):
        return cls.from_image(as_image(image), hash_size)

    @classmethod
    def _prepare_image(cls, image: PILImage, hash_size: int = 8) -> PILImage:
        """
        Adding this thumbnail step provides an overall ~2x perf boost.  Performance gains come from having a smaller
        area to convert from mode=RGB(A) to mode=L, and during the resizing step with `ANTIALIASING` later.

        Originally based on `a post in this issue <https://github.com/JohannesBuchner/imagehash/issues/128>`__.

        The original implementation used a slower loop instead of using `math.log2`, and it used a 4x multiplier, which
        resulted in both overly-permissive and less accurate matching, depending on when it was applied relative to
        converting the image to mode=L.  The x16 multiplier used here works for either order, and seems to allow
        additional detail to be retained while still providing the same magnitude of performance improvement.  The
        conversion to mode=L is forced to occur at the end of this method, after calling thumbnail, due to improved
        performance when using this order.
        """
        width, height = image.size
        # Note: math.log2 is 3-4x faster than numpy.log2 for this use case
        if width < height:
            factor = 2 ** int(log2(width / ((hash_size + cls._hash_x_offset) * 16)))
        else:
            factor = 2 ** int(log2(height / ((hash_size + cls._hash_y_offset) * 16)))

        if factor > 1:
            image.thumbnail((width / factor, height / factor), NEAREST)  # This doesn't return anything

        return image.convert('L')

    # endregion

    @cached_property
    def hex(self) -> str:
        return self.array.tobytes().hex().upper()

    @cached_property
    def hash_bits(self) -> NDArray:
        """
        A 64-element array of 0s and 1s representing this hash.  Calculating hamming distance using this has the same
        results as when using an array of bools, but this requires fewer steps to reconstruct from a serialized value.

        To transform the array back into an 8x8 array of bools (to match the format that it was in before ``packbits``
        was called on it), use ``unpackbits(self.array).view(bool).reshape((8, 8))``.
        """
        return unpackbits(self.array)

    # region Internal / Dunder Methods

    def __repr__(self) -> str:
        return f'<{self.__class__.__name__}[{self.hex}, size={self.array.size}]>'

    def __getstate__(self):
        return self.array.tobytes()

    def __setstate__(self, state):
        # Note: This does not currently handle any hashes with a size != 8 / a length != 64 bits
        # self.array = frombuffer(state, dtype=uint64).view(uint8)
        self.array = frombuffer(state, dtype=uint8)

    def __len__(self) -> int:
        """The number of bits in this hash"""
        return self.array.size * 8  # self.array contains uint8 values, so *8 to get bits

    def __eq__(self, other: ImageHashBase) -> bool:
        return (self.array == other.array).all()  # noqa

    def __hash__(self) -> int:
        return hash(self.__class__) ^ hash(self.hex)

    # endregion

    # region Comparison Methods

    def __sub__(self, other: ImageHashBase) -> int:
        if self.array.size != other.array.size:
            raise ValueError(f'Unable to compare {self} with {other} due to incompatible shapes')
        return count_nonzero(self.hash_bits != other.hash_bits)

    difference = __sub__

    def relative_difference(self, other: ImageHashBase) -> float:
        # Closer to 0 means fewer differences, closer to 1 means more differences
        return (self - other) / len(self)

    __or__ = relative_difference

    # endregion


class HorizontalDifferenceHash(ImageHashBase, hash_x_offset=1, mode='horizontal', aliases=('difference',)):
    """
    Computes differences horizontally.  Based on ``dhash`` from ``imagehash``, which uses the following approach:
    http://www.hackerfactor.com/blog/index.php?/archives/529-Kind-of-Like-That.html
    """

    @classmethod
    def from_image(cls, image: PILImage, hash_size: int = 8, skip_prep: bool = False) -> HorizontalDifferenceHash:
        if not skip_prep:  # Optimization for hashing multiple transforms of an image, already converted to grayscale
            image = cls._prepare_image(image, hash_size)

        pixels = asarray(image.resize((hash_size + 1, hash_size), ANTIALIAS))  # shape: (height, width, channels)
        # compute differences between columns
        return cls(packbits(pixels[:, 1:] > pixels[:, :-1]))  # noqa  # Note: Original did not call packbits here


DifferenceHash = HorizontalDifferenceHash


class VerticalDifferenceHash(ImageHashBase, hash_y_offset=1, mode='vertical'):
    """
    Computes differences vertically.  Based on ``dhash_vertical`` from ``imagehash``, which uses the following approach:
    http://www.hackerfactor.com/blog/index.php?/archives/529-Kind-of-Like-That.html
    """

    @classmethod
    def from_image(cls, image: PILImage, hash_size: int = 8, skip_prep: bool = False) -> VerticalDifferenceHash:
        if not skip_prep:  # Optimization for hashing multiple transforms of an image, already converted to grayscale
            image = cls._prepare_image(image, hash_size)

        pixels = asarray(image.resize((hash_size, hash_size + 1), ANTIALIAS))  # shape: (height, width, channels)
        # compute differences between columns
        return cls(packbits(pixels[1:, :] > pixels[:-1, :]))  # noqa  # Note: Original did not call packbits here


class WaveletHash(ImageHashBase, mode='wavelet'):
    """
    Wavelet Hash computation.  Based on ``whash`` from ``imagehash``, which was based on the following approach:
    https://www.kaggle.com/c/avito-duplicate-ads-detection/
    """

    @classmethod
    def from_image(
        cls,
        image: PILImage,
        hash_size: int = 8,
        skip_prep: bool = False,
        *,
        image_scale: int = None,
        mode: Literal['haar', 'db4'] = 'haar',
        remove_max_haar_ll: bool = True,
    ) -> WaveletHash:
        if wavedec2 is None:
            raise RuntimeError('Missing optional dependency: pywt')
        if image_scale is None:
            image_scale = max(2 ** int(log2(min(image.size))), hash_size)
        # elif image_scale & (image_scale - 1) != 0:
        #     raise ValueError(f'Invalid {image_scale=} - it must be a power of 2')
        # elif hash_size & (hash_size - 1) != 0:
        #     raise ValueError(f'Invalid {hash_size=} - it must be a power of 2')

        ll_max_level = int(log2(image_scale))
        if (level := int(log2(hash_size))) > ll_max_level:
            raise ValueError(f'Invalid {hash_size=} for {image_scale=}')

        # log.debug(f'Using {image.size=}, {image_scale=}, {hash_size=}, {ll_max_level=}, {level=}')
        if not skip_prep:  # Optimization for hashing multiple transforms of an image, already converted to grayscale
            image = image.convert('L')
        pixels = asarray(image.resize((image_scale, image_scale), ANTIALIAS)) / 255  # shape: (height, width, channels)
        # Remove low level frequency LL(max_ll) if @remove_max_haar_ll using haar filter
        if remove_max_haar_ll:
            coefficients = wavedec2(pixels, 'haar', level=ll_max_level)
            coefficients[0] *= 0
            pixels = waverec2(coefficients, 'haar')

        # Use LL(K) as freq, where K is log2(@hash_size)
        dwt_low = wavedec2(pixels, mode, level=ll_max_level - level)[0]
        # Subtract median and compute hash
        return cls(packbits(dwt_low > median(dwt_low)))  # Note: Original did not call packbits here


def get_hash_class(hash_mode: str) -> Type[HorizontalDifferenceHash] | Type[VerticalDifferenceHash] | Type[WaveletHash]:
    try:
        return HASH_MODES[hash_mode]
    except KeyError as e:
        raise ValueError(f'Invalid {hash_mode=} - expected one of:' + ', '.join(HASH_MODES)) from e
