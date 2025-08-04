from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from itertools import product
from pathlib import Path
from typing import TYPE_CHECKING, BinaryIO, Generic, Sequence, Type, TypeVar

from PIL.Image import Transpose, Image as PILImage, open as open_image

from ..utils import as_image
from .single import ImageHashBase

if TYPE_CHECKING:
    from ..typing import ImageType

__all__ = ['MULTI_MODES', 'MultiHash', 'RotatedMultiHash', 'get_multi_class']
log = logging.getLogger(__name__)

HT = TypeVar('HT', bound='ImageHashBase')

MULTI_MODES: dict[str, Type[MultiHash]] = {}


class MultiHash(Generic[HT], ABC):
    __slots__ = ('hashes',)
    mode: str
    hashes: Sequence[HT]

    def __init_subclass__(cls, mode: str, **kwargs):
        super().__init_subclass__(**kwargs)
        MULTI_MODES[mode] = cls
        cls.mode = mode

    def __init__(self, hashes: Sequence[HT]):
        self.hashes = hashes

    @classmethod
    def from_any(cls, image: ImageType, hash_cls: Type[HT], **kwargs) -> MultiHash[HT]:
        return cls.from_image(as_image(image), hash_cls, **kwargs)

    @classmethod
    def from_file(cls, file: Path | BinaryIO, hash_cls: Type[HT], **kwargs) -> MultiHash[HT]:
        return cls.from_image(open_image(file), hash_cls, **kwargs)

    @classmethod
    @abstractmethod
    def from_image(cls, image: PILImage, hash_cls: Type[HT], *, hash_size: int = 8) -> MultiHash[HT]:
        raise NotImplementedError

    @abstractmethod
    def difference(self, other) -> int:
        raise NotImplementedError

    @abstractmethod
    def relative_difference(self, other) -> float:
        raise NotImplementedError

    def __eq__(self, other: MultiHash[HT]) -> bool:
        if len(self.hashes) != len(other.hashes):
            return False
        return all((s == o).all() for s, o in zip(self.hashes, other.hashes))  # noqa

    def __lt__(self, other: MultiHash[HT]) -> bool:
        return any((s.array < o.array).sum() for s, o in zip(self.hashes, other.hashes))  # noqa

    def __gt__(self, other: MultiHash[HT]) -> bool:
        return any((s.array > o.array).sum() for s, o in zip(self.hashes, other.hashes))  # noqa


class RotatedMultiHash(MultiHash, mode='rotated'):
    __slots__ = ()

    @classmethod
    def from_image(cls, image: PILImage, hash_cls: Type[HT], *, hash_size: int = 8) -> RotatedMultiHash[HT]:
        gray_img = hash_cls._prepare_image(image, hash_size)
        # Since the same approach is used for the DB entries and during lookup, only 3 hashes are necessary.
        hashes = [
            hash_cls.from_image(gray_img, hash_size=hash_size, skip_prep=True),
            hash_cls.from_image(gray_img.transpose(Transpose.ROTATE_90), hash_size=hash_size, skip_prep=True),
            hash_cls.from_image(gray_img.transpose(Transpose.ROTATE_180), hash_size=hash_size, skip_prep=True),
        ]
        # Omitted: Transpose.ROTATE_270
        return cls(hashes)

    def difference(self, other: RotatedMultiHash[HT] | HT) -> int:
        if isinstance(other, ImageHashBase):
            return min(h - other for h in self.hashes)
        elif not isinstance(other, self.__class__):
            raise TypeError(f'Unable to compare {self} with {other}')
        return min(s - o for s, o in product(self.hashes, other.hashes))

    __sub__ = difference

    def relative_difference(self, other: RotatedMultiHash[HT]) -> float:
        return self.difference(other) / len(self.hashes[0])

    __or__ = relative_difference


def get_multi_class(multi_mode: str) -> Type[RotatedMultiHash] | Type[MultiHash]:
    try:
        return MULTI_MODES[multi_mode]
    except KeyError as e:
        raise ValueError(f'Invalid {multi_mode=} - expected one of:' + ', '.join(MULTI_MODES)) from e
