"""
Utilities for comparing images

:author: Doug Skrypa
"""

from __future__ import annotations

import logging
from collections import defaultdict
from functools import cached_property, partialmethod, wraps
from typing import TYPE_CHECKING
from weakref import WeakKeyDictionary

import numpy
from numpy import asarray, float64
from PIL.Image import Image as PILImage, open as open_image
try:
    from skimage.metrics import structural_similarity
except ImportError:
    structural_similarity = None

if TYPE_CHECKING:
    from pathlib import Path
    from numpy.typing import ArrayLike, NDArray
    from .typing import Size, NP_Image, NP_Gray

__all__ = ['ComparableImage']
log = logging.getLogger(__name__)


def comparison(func):
    name = func.__name__

    @wraps(func)
    def wrapper(*args):  # Makes PyCharm type checking happier than the more explicit version
        self, other = args  # type: ComparableImage, ComparableImage
        if (value := self._computed[name].get(other)) is None:
            self._computed[name][other] = value = func(self, other)
        return value
    return wrapper


class ComparableImage:
    def __init__(
        self,
        image: PILImage | str | Path,
        gray: bool = True,
        normalize: bool = True,
        max_width: int = None,
        max_height: int = None,
        _sizes: dict[Size, ComparableImage] = None,
    ):
        self.image = image if isinstance(image, PILImage) else open_image(image)
        self._gray = gray
        self._normalize = normalize
        self._max_width = max_width
        self._max_height = max_height
        self._as_size: dict[Size, ComparableImage] = _sizes or {}
        self._as_size[self.image.size] = self
        self._computed = defaultdict(WeakKeyDictionary)

    def __repr__(self) -> str:
        return (
            f'<{self.__class__.__name__}({self.image!r}, gray={self._gray}, normalize={self._normalize}, '
            f'max_width={self._max_width}, max_height={self._max_height})>'
        )

    def is_same_as(self, other: ComparableImage, taxi: float = 2, mse: float = 20, mssim: float = 0.975) -> bool:
        """
        :param other: The ComparableImage with which this image should be compared
        :param taxi: Maximum threshold for taxicab distance (per pixel)
        :param mse: Maximum threshold for mean squared error
        :param mssim: Minimum threshold for mean structural similarity
        :return: True if this image is the same as other within the specified thresholds, False otherwise
        """
        _self, other = self.compatible_sizes(other)
        if _self.taxicab_distance(other)[1] > taxi:
            return False
        elif _self.mean_squared_error(other) > mse:
            return False
        elif _self.mean_structural_similarity(other) < mssim:
            return False
        return True

    def is_similar_to(self, other: ComparableImage, taxi: float = 10, mse: float = 300, mssim: float = 0.8) -> bool:
        """
        :param other: The ComparableImage with which this image should be compared
        :param taxi: Maximum threshold for taxicab distance (per pixel)
        :param mse: Maximum threshold for mean squared error
        :param mssim: Minimum threshold for mean structural similarity
        :return: True if this image is similar to other within the specified thresholds, False otherwise
        """
        _self, other = self.compatible_sizes(other)
        if _self.taxicab_distance(other)[1] > taxi:
            return False
        elif _self.mean_squared_error(other) > mse:
            return False
        elif _self.mean_structural_similarity(other) < mssim:
            return False
        return True

    @cached_property
    def is_gray(self) -> bool:
        return self._gray or len(self.pixel_array.shape) == 2  # 2 dimensions indicates only 1 channel

    @comparison
    def taxicab_distance(self, other: ComparableImage) -> tuple[float, float]:
        """
        Based on: https://gist.github.com/astanin/626356

        :param other: The ComparableImage with which this image should be compared
        :return: The Manhattan/taxicab distance between this image and other, and the per-pixel value
        """
        _self, other = self.compatible_sizes(other)
        diff = _self.float_array - other.float_array
        m_norm = numpy.sum(abs(diff))  # Manhattan norm / taxicab distance
        return m_norm, m_norm / _self.float_array.size

    @comparison
    def mean_squared_error(self, other: ComparableImage) -> float:
        """
        :param other: The ComparableImage with which this image should be compared
        :return float: Lower values indicate higher similarity
        """
        _self, other = self.compatible_sizes(other)
        return numpy.mean((_self.float_array - other.float_array) ** 2, dtype=float64)

    @comparison
    def mean_structural_similarity(self, other: ComparableImage) -> float:
        """
        :param other: The ComparableImage with which this image should be compared
        :return: A number between 0 and 1.  Larger values indicate higher similarity.
        """
        if structural_similarity is None:
            raise RuntimeError('Unable to calculate mean_structural_similarity - missing dependency: scikit-image')

        _self, other = self.compatible_sizes(other)
        # TODO: Comparing a 1600x925 image that has been cropped to 1600x901 to remove a header receives very low
        #  similarity scores across the board... Maybe compatible_sizes is providing problematic output?
        if _self.is_gray or other.is_gray:
            return structural_similarity(_self.gray_pixel_array, other.gray_pixel_array, multichannel=False)

        self_arr, other_arr = _self.pixel_array, other.pixel_array
        if self_arr.shape[2] != other_arr.shape[2]:
            if self_arr.shape[2] == 4:  # self is RGBA and assume other is RGB
                self_arr = self_arr[:,:,:3]  # ignore the alpha channel
            else:  # assume self is RGB and other is RGBA
                other_arr = other_arr[:,:,:3]

        return structural_similarity(self_arr, other_arr, multichannel=True, channel_axis=2)

    @comparison
    def zero_norm(self, other: ComparableImage) -> tuple[float, float]:
        """
        Based on: https://gist.github.com/astanin/626356

        Does not seem to be useful.

        :param other: The ComparableImage with which this image should be compared
        :return: The zero norm between this image and other, and the per-pixel value
        """
        _self, other = self.compatible_sizes(other)
        diff = _self.float_array - other.float_array
        # z_norm = norm(diff.ravel(), 0)  # Zero norm
        # This should be equivalent to scipy.linalg.norm, and allows for dropping the scipy dependency:
        z_norm = numpy.linalg.norm(numpy.asarray_chkfinite(diff.ravel()), ord=0)  # Zero norm
        return z_norm, z_norm / _self.float_array.size  # noqa

    def normalized_root_mse(self, other: ComparableImage, normalization: str = 'euclidean') -> float:
        """
        Based on :func:`skimage.metrics.normalized_root_mse`.

        This method is not useful for determining whether two images are the same, and is intended for use on two images
        that are already known to be the same.

        :param other: The ComparableImage with which this image should be compared
        :param normalization: One of 'euclidean', 'min-max', 'mean'
        :return:
        """
        _self, other = self.compatible_sizes(other)
        normalization = normalization.lower()
        if normalization == 'euclidean':
            denom = numpy.sqrt(numpy.mean((_self.float_array * _self.float_array), dtype=numpy.float64))
        elif normalization == 'min-max':
            denom = _self.float_array.max() - _self.float_array.min()
        elif normalization == 'mean':
            denom = _self.float_array.mean()
        else:
            raise ValueError(f'Unsupported {normalization=}')
        return numpy.sqrt(_self.mean_squared_error(other)) / denom

    euclidean_root_mse = partialmethod(normalized_root_mse, normalization='euclidean')
    min_max_root_mse = partialmethod(normalized_root_mse, normalization='min-max')
    mean_root_mse = partialmethod(normalized_root_mse, normalization='mean')

    @comparison
    def peak_signal_noise_ratio(self, other: ComparableImage, data_range=None) -> float:
        """
        The ratio between the maximum possible power of a signal and the power of corrupting noise that affects the
        fidelity of its representation.

        If this image is an original, uncompressed image, and other is a lossily compressed version, then the returned
        value provides some indication of the quality of the other version.

        This method is not useful for determining whether two images are the same, and is intended for use on two images
        that are already known to be the same.

        Based on :func:`skimage.metrics.peak_signal_noise_ratio`.

        :param other: The ComparableImage with which this image should be compared
        :param data_range:
        :return: The ratio in decibels.  Higher values generally indicate higher quality.
        """
        _self, other = self.compatible_sizes(other)
        mse = _self.mean_squared_error(other)
        if mse == 0:
            return float('inf')
        elif data_range is None:
            dmin, dmax = dtype_ranges()[_self.pixel_array.dtype.type]
            true_min, true_max = numpy.min(_self.pixel_array), numpy.max(_self.pixel_array)
            if true_max > dmax or true_min < dmin:
                raise ValueError(
                    f'{self} has intensity values outside the range expected for its data type. Please manually '
                    'specify the data_range'
                )
            if true_min >= 0:  # most common case (255 for uint8, 1 for float)
                data_range = dmax
            else:
                data_range = dmax - dmin

        return 10 * numpy.log10((data_range ** 2) / mse)

    @cached_property
    def pixel_array(self) -> NP_Image:
        mode = 'L' if self._gray else 'RGBA' if 'A' in self.image.mode else 'RGB'
        if mode != self.image.mode:
            return asarray(self.image.convert(mode))
        else:
            return asarray(self.image)

    @cached_property
    def gray_pixel_array(self) -> NP_Gray:
        return self.pixel_array if self._gray else asarray(self.image.convert('L'))

    @cached_property
    def float_array(self) -> NDArray[float64]:
        arr = self.pixel_array.astype(float)
        return _normalize(arr) if self._normalize else arr

    def as_compatible_size(self, other: ComparableImage) -> ComparableImage:
        max_widths = list(filter(None, (img._max_width for img in (self, other))))
        max_heights = list(filter(None, (img._max_height for img in (self, other))))
        if self.image.size == other.image.size and not max_widths and not max_heights:
            return self

        min_width = min([self.image.width, other.image.width] + max_widths)
        min_height = min([self.image.height, other.image.height] + max_heights)
        min_size = (min_width, min_height)
        if min_size not in self._as_size:  # self would already be there; returned value adds itself
            image = _resize(self.image, min_width)
            image = _crop(image, min_width, min_height)
            return ComparableImage(image, self._gray, self._normalize, self._max_width, self._max_height, self._as_size)

        return self._as_size[min_size]

    def compatible_sizes(self, other: ComparableImage) -> tuple[ComparableImage, ComparableImage]:
        _self = self.as_compatible_size(other)
        other = other.as_compatible_size(self)
        return _self, other


def _resize(img: PILImage, new_width: int) -> PILImage:
    if img.width > new_width:
        new_height = int(round(new_width * img.height / img.width))
        log.debug(f'Resizing {img} to {new_width}x{new_height}')
        return img.resize((new_width, new_height))
    return img


def _crop(img: PILImage, width: int, height: int) -> PILImage:
    if img.width > width or img.height > height:
        log.debug(f'Cropping {img} from {img.width}x{img.height} to {width}x{height}')
        return img.crop((0, 0, width, height))
    return img


def _normalize(img_arr: ArrayLike) -> ArrayLike:
    # Compensate for exposure difference
    img_min = img_arr.min()
    img_range = (img_arr.max() - img_min) or 1
    return (img_arr - img_min) * 255 / img_range


def dtype_ranges():
    try:
        from skimage.util.dtype import dtype_range
    except ImportError:
        pass
    else:
        return dtype_range

    try:
        return dtype_ranges._value
    except AttributeError:
        # Below was copied from scikit-image on 2021-10-16:
        np = numpy
        _integer_types = (
            np.byte, np.ubyte,  # 8 bits
            np.short, np.ushort,  # 16 bits
            np.intc, np.uintc,  # 16 or 32 or 64 bits
            int, np.int_, np.uint,  # 32 or 64 bits
            np.longlong, np.ulonglong,  # 64 bits
        )
        _integer_ranges = {t: (np.iinfo(t).min, np.iinfo(t).max) for t in _integer_types}
        dtype_range = {
            bool: (False, True),
            np.bool_: (False, True),
            np.bool8: (False, True),
            float: (-1, 1),
            np.float_: (-1, 1),
            np.float16: (-1, 1),
            np.float32: (-1, 1),
            np.float64: (-1, 1),
        }
        dtype_range.update(_integer_ranges)
        dtype_ranges._value = dtype_range
        return dtype_range
