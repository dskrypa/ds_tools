"""
Utilities for comparing images

:author: Doug Skrypa
"""

import logging
from collections import defaultdict
from functools import cached_property, partialmethod, wraps
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING, Union
from weakref import WeakKeyDictionary

import numpy
from PIL import Image, ImageOps
from imageio import imread
from skimage.metrics import structural_similarity
from skimage.util.dtype import dtype_range
from scipy.linalg import norm

if TYPE_CHECKING:
    from numpy.typing import ArrayLike
    from .utils import Size

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
        image: Union[Image.Image, str, Path],
        gray: bool = True,
        normalize: bool = True,
        max_width: int = None,
        max_height: int = None,
        compare_as: str = None,
        _sizes: dict['Size', 'ComparableImage'] = None,
    ):
        self.image = image if isinstance(image, Image.Image) else Image.open(image)
        self._gray = gray
        self._normalize = normalize
        self._max_width = max_width
        self._max_height = max_height
        self._compare_as = compare_as  # If one image is jpeg, both should use jpeg. Only use png if both are webp/png
        self._as_size: dict['Size', 'ComparableImage'] = _sizes or {}
        self._as_size[self.image.size] = self
        self._computed = defaultdict(WeakKeyDictionary)

    def __repr__(self):
        return (
            f'<{self.__class__.__name__}({self.image!r}, gray={self._gray}, normalize={self._normalize}, '
            f'max_width={self._max_width}, max_height={self._max_height}, compare_as={self._compare_as!r})>'
        )

    def is_same_as(self, other: 'ComparableImage', taxi: float = 2, mse: float = 20, mssim: float = 0.975) -> bool:
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

    def is_similar_to(self, other: 'ComparableImage', taxi: float = 10, mse: float = 300, mssim: float = 0.8) -> bool:
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

    @comparison
    def taxicab_distance(self, other: 'ComparableImage') -> tuple[float, float]:
        """
        Based on: https://gist.github.com/astanin/626356

        :param other: The ComparableImage with which this image should be compared
        :return: The Manhattan/taxicab distance between this image and other, and the per-pixel value
        """
        _self, other = self.compatible_sizes(other)
        diff = _self.float_array - other.float_array
        m_norm = numpy.sum(abs(diff))  # Manhattan norm / taxicab distance
        # noinspection PyTypeChecker
        return m_norm, m_norm / _self.float_array.size

    @comparison
    def mean_squared_error(self, other: 'ComparableImage') -> float:
        """
        :param other: The ComparableImage with which this image should be compared
        :return float: Lower values indicate higher similarity
        """
        _self, other = self.compatible_sizes(other)
        # noinspection PyTypeChecker
        return numpy.mean((_self.float_array - other.float_array) ** 2, dtype=numpy.float64)

    @comparison
    def mean_structural_similarity(self, other: 'ComparableImage') -> float:
        """
        :param other: The ComparableImage with which this image should be compared
        :return: A number between 0 and 1.  Larger values indicate higher similarity.
        """
        _self, other = self.compatible_sizes(other)
        return structural_similarity(_self.imread_array, other.imread_array, multichannel=not self._gray)

    @comparison
    def zero_norm(self, other: 'ComparableImage') -> tuple[float, float]:
        """
        Based on: https://gist.github.com/astanin/626356

        Does not seem to be useful.

        :param other: The ComparableImage with which this image should be compared
        :return: The zero norm between this image and other, and the per-pixel value
        """
        _self, other = self.compatible_sizes(other)
        diff = _self.float_array - other.float_array
        z_norm = norm(diff.ravel(), 0)  # Zero norm
        return z_norm, z_norm / _self.float_array.size

    def normalized_root_mse(self, other: 'ComparableImage', normalization: str = 'euclidean') -> float:
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
    def peak_signal_noise_ratio(self, other: 'ComparableImage', data_range=None) -> float:
        """
        The ratio between the maxiumum possible power of a signal and the power of corrupting noise that affects the
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
            dmin, dmax = dtype_range[_self.imread_array.dtype.type]
            true_min, true_max = numpy.min(_self.imread_array), numpy.max(_self.imread_array)
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
    def imread_array(self) -> 'ArrayLike':
        image = ImageOps.grayscale(self.image) if self._gray else self.image
        bio = BytesIO()
        image.save(bio, self._compare_as or 'jpeg')
        return imread(bio.getvalue())

    @cached_property
    def float_array(self) -> 'ArrayLike':
        arr = self.imread_array.astype(float)
        if self._normalize:
            arr = _normalize(arr)
        return arr

    def as_compatible_size(self, other: 'ComparableImage') -> 'ComparableImage':
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
            return ComparableImage(
                image, self._gray, self._normalize, self._max_width, self._max_height, self._compare_as, self._as_size
            )
        return self._as_size[min_size]

    def compatible_sizes(self, other: 'ComparableImage') -> tuple['ComparableImage', 'ComparableImage']:
        _self = self.as_compatible_size(other)
        other = other.as_compatible_size(self)
        return _self, other


def _resize(img: Image.Image, new_width: int) -> Image.Image:
    if img.width > new_width:
        new_height = int(round(new_width * img.height / img.width))
        log.debug(f'Resizing {img} to {new_width}x{new_height}')
        return img.resize((new_width, new_height))
    return img


def _crop(img: Image.Image, width: int, height: int) -> Image.Image:
    if img.width > width or img.height > height:
        log.debug(f'Cropping {img} from {img.width}x{img.height} to {width}x{height}')
        return img.crop((0, 0, width, height))
    return img


def _normalize(img_arr: 'ArrayLike') -> 'ArrayLike':
    # Compensate for exposure difference
    img_min = img_arr.min()
    img_range = (img_arr.max() - img_min) or 1
    return (img_arr - img_min) * 255 / img_range
