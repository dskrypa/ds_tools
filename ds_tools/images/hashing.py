from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
from hashlib import sha256
from io import BytesIO
from itertools import product
from pathlib import Path
from sqlite3 import register_adapter
from typing import TYPE_CHECKING, Iterable, Iterator, Literal, Type, Collection, BinaryIO

from numpy import transpose, bitwise_and, full as np_full, invert as np_invert
from numpy import array, asarray, frombuffer, packbits, unpackbits, nonzero, count_nonzero, log2, median
from numpy import uint8, uint16, uint64, float32
from numpy.typing import NDArray
from PIL import UnidentifiedImageError
from PIL.Image import Resampling, Transpose, Image as PILImage, open as open_image  # noqa
from PIL.ImageFilter import GaussianBlur, MedianFilter
from sqlalchemy import create_engine, Column, Integer, String, ForeignKey, or_, and_, text
from sqlalchemy.sql.functions import count
from sqlalchemy.orm import Query, relationship, scoped_session, sessionmaker, DeclarativeBase, Mapped, aliased
from tqdm import tqdm

try:
    from pywt import wavedec2, waverec2
except ImportError:
    wavedec2 = waverec2 = None

from ds_tools.caching.decorators import cached_property
from .utils import ImageType, as_image

if TYPE_CHECKING:
    from os import stat_result

__all__ = [
    'ImageHashBase', 'DifferenceHash', 'HorizontalDifferenceHash', 'VerticalDifferenceHash', 'WaveletHash',
    'MultiHash', 'RotatedMultiHash', 'CropResistantMultiHash',
    'Directory', 'ImageFile', 'ImageHash', 'ImageDB',
]
log = logging.getLogger(__name__)

Pixel = tuple[int, int]
ANTIALIAS = Resampling.LANCZOS

# region Image Hash


class ImageHashBase(ABC):
    """
    A 64-bit hash of an image.  Based heavily on the implementation in
    `imagehash<https://github.com/JohannesBuchner/imagehash>`__, but with some differences / optimizations for
    this use case.  Most notably, the hash array is stored as / expected to be a 1x8 array of uint8 values
    instead of an 8x8 array of bools.
    """
    array: NDArray[uint8]

    def __init__(self, hash_array: NDArray[uint8]):
        """
        :param hash_array: A 1x8 numpy array of uint8 values.  If you have an array of bools or 1/0s, use
          ``numpy.packbits`` on it to obtain the value expected here.
        """
        self.array = hash_array

    def __getstate__(self):
        return self.array.tobytes()

    def __setstate__(self, state):
        # Note: This does not currently handle any hashes with a size != 8 / a length != 64 bits
        self.array = frombuffer(state, dtype=uint64).view(uint8)

    @classmethod
    @abstractmethod
    def from_image(cls, image: PILImage, hash_size: int = 8, convert: bool = True):
        raise NotImplementedError

    @classmethod
    def from_any(cls, image: ImageType | str, hash_size: int = 8):
        return cls.from_image(as_image(image), hash_size)

    def __repr__(self) -> str:
        return f'<{self.__class__.__name__}[{self.hex}, size={self.array.size}]>'

    @cached_property(block=False)
    def hex(self) -> str:
        return self.array.tobytes().hex().upper()

    @cached_property(block=False)
    def hash_bits(self) -> NDArray:
        """
        A 64-element array of 0s and 1s representing this hash.  Calculating hamming distance using this has the same
        results as when using an array of bools, but this requires fewer steps to reconstruct from a serialized value.

        To transform the array back into an 8x8 array of bools (to match the format that it was in before ``packbits``
        was called on it), use ``unpackbits(self.array).view(bool).reshape((8, 8))``.
        """
        return unpackbits(self.array)

    @cached_property(block=False)
    def uint16(self) -> NDArray[uint16]:  # No longer used
        return self.array.view(uint16)

    def __len__(self) -> int:
        """The number of bits in this hash"""
        return self.array.size * 8  # self.array contains uint8 values, so *8 to get bits

    def __eq__(self, other: ImageHashBase) -> bool:
        return (self.array == other.array).all()

    def __hash__(self) -> int:
        return hash(self.__class__) ^ hash(self.hex)

    def __sub__(self, other: ImageHashBase) -> int:
        if self.array.size != other.array.size:
            raise ValueError(f'Unable to compare {self} with {other} due to incompatible shapes')
        return count_nonzero(self.hash_bits != other.hash_bits)

    difference = __sub__

    def relative_difference(self, other: ImageHashBase) -> float:
        # Closer to 0 means fewer differences, closer to 1 means more differences
        return (self - other) / len(self)

    __or__ = relative_difference


class HorizontalDifferenceHash(ImageHashBase):
    """
    Computes differences horizontally.  Based on ``dhash`` from ``imagehash``, which uses the following approach:
    http://www.hackerfactor.com/blog/index.php?/archives/529-Kind-of-Like-That.html
    """

    @classmethod
    def from_image(cls, image: PILImage, hash_size: int = 8, convert: bool = True) -> HorizontalDifferenceHash:
        if convert:  # Optimization for hashing multiple transforms of the same image, already converted to grayscale
            image = image.convert('L')
        pixels = asarray(image.resize((hash_size + 1, hash_size), ANTIALIAS))  # noqa
        # compute differences between columns
        return cls(packbits(pixels[:, 1:] > pixels[:, :-1]))  # noqa  # Note: Original did not call packbits here


DifferenceHash = HorizontalDifferenceHash


class VerticalDifferenceHash(ImageHashBase):
    """
    Computes differences vertically.  Based on ``dhash_vertical`` from ``imagehash``, which uses the following approach:
    http://www.hackerfactor.com/blog/index.php?/archives/529-Kind-of-Like-That.html
    """

    @classmethod
    def from_image(cls, image: PILImage, hash_size: int = 8, convert: bool = True) -> VerticalDifferenceHash:
        if convert:  # Optimization for hashing multiple transforms of the same image, already converted to grayscale
            image = image.convert('L')
        pixels = asarray(image.resize((hash_size, hash_size + 1), ANTIALIAS))  # noqa
        # compute differences between columns
        return cls(packbits(pixels[1:, :] > pixels[:-1, :]))  # noqa  # Note: Original did not call packbits here


class WaveletHash(ImageHashBase):
    """
    Wavelet Hash computation.  Based on ``whash`` from ``imagehash``, which was based on the following approach:
    https://www.kaggle.com/c/avito-duplicate-ads-detection/
    """

    @classmethod
    def from_image(
        cls,
        image: PILImage,
        hash_size: int = 8,
        convert: bool = True,
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
        if convert:  # Optimization for hashing multiple transforms of the same image, already converted to grayscale
            image = image.convert('L')
        pixels = asarray(image.resize((image_scale, image_scale), ANTIALIAS)) / 255  # noqa
        # Remove low level frequency LL(max_ll) if @remove_max_haar_ll using haar filter
        if remove_max_haar_ll:
            coefficients = wavedec2(pixels, 'haar', level=ll_max_level)
            coefficients[0] *= 0
            pixels = waverec2(coefficients, 'haar')

        # Use LL(K) as freq, where K is log2(@hash_size)
        dwt_low = wavedec2(pixels, mode, level=ll_max_level - level)[0]
        # Subtract median and compute hash
        return cls(packbits(dwt_low > median(dwt_low)))  # Note: Original did not call packbits here


# endregion

# HASH_CLS = WaveletHash
HASH_CLS = DifferenceHash

# region Multi-Hash


class MultiHash(ABC):
    __slots__ = ('hashes',)

    def __init__(self, hashes: list[ImageHashBase]):
        self.hashes = hashes

    @classmethod
    def from_any(cls, image: ImageType, *args, **kwargs) -> MultiHash:
        return cls.from_image(as_image(image), *args, **kwargs)

    @classmethod
    def from_file(cls, file: Path | BinaryIO, *args, **kwargs) -> MultiHash:
        return cls.from_image(open_image(file), *args, **kwargs)

    @classmethod
    @abstractmethod
    def from_image(cls, image: PILImage, hash_cls: Type[ImageHashBase] = HASH_CLS) -> MultiHash:
        raise NotImplementedError

    @abstractmethod
    def difference(self, other) -> int:
        raise NotImplementedError

    @abstractmethod
    def relative_difference(self, other) -> float:
        raise NotImplementedError

    def __eq__(self, other: MultiHash) -> bool:
        if len(self.hashes) != len(other.hashes):
            return False
        return all((s == o).all() for s, o in zip(self.hashes, other.hashes))  # noqa

    def __lt__(self, other: MultiHash) -> bool:
        return any((s.array < o.array).sum() for s, o in zip(self.hashes, other.hashes))  # noqa

    def __gt__(self, other: MultiHash) -> bool:
        return any((s.array > o.array).sum() for s, o in zip(self.hashes, other.hashes))  # noqa


class RotatedMultiHash(MultiHash):
    __slots__ = ()

    @classmethod
    def from_image(cls, image: PILImage, hash_cls: Type[ImageHashBase] = HASH_CLS) -> MultiHash:
        gray_img = image.convert('L')
        hashes = [hash_cls.from_image(gray_img, convert=False)]
        # Since the same approach is used for the DB entries and during lookup, only 3 hashes are necessary.
        for angle in (Transpose.ROTATE_90, Transpose.ROTATE_180):  # Omitted: Transpose.ROTATE_270
            hashes.append(hash_cls.from_image(gray_img.transpose(angle), convert=False))
        return cls(hashes)

    def difference(self, other: MultiHash | ImageHashBase) -> int:
        if isinstance(other, ImageHashBase):
            return min(h - other for h in self.hashes)
        elif not isinstance(other, self.__class__):
            raise TypeError(f'Unable to compare {self} with {other}')
        return min(s - o for s, o in product(self.hashes, other.hashes))

    __sub__ = difference

    def relative_difference(self, other: MultiHash) -> float:
        return self.difference(other) / len(self.hashes[0])

    __or__ = relative_difference


# region Crop-Resistant Hash


class CropResistantMultiHash(MultiHash):
    """
    Based heavily on the ``ImageMultiHash`` class and ``crop_resistant_hash`` function in ``imagehash``, with a few
    optimizations around segmentation.
    """
    __slots__ = ()

    @classmethod
    def from_image(
        cls,
        image: PILImage,
        hash_cls: Type[ImageHashBase] = HASH_CLS,
        segment_limit: int = None,
        segment_threshold: int = 128,
        min_segment_size: int = 500,
        pre_segment_size: int = 300,
    ) -> CropResistantMultiHash:
        gray_img = image.convert('L')  # Note: original used the original image in most places where this is used
        # noinspection PyTypeChecker
        pixels = array(
            gray_img.resize((pre_segment_size, pre_segment_size), ANTIALIAS).filter(GaussianBlur()).filter(MedianFilter())
        ).astype(float32)
        segments = _find_all_segments(pixels, segment_threshold, min_segment_size)
        if not segments:                        # If there are no segments, have 1 segment including the whole image
            segments.append({(0, 0), (pre_segment_size - 1, pre_segment_size - 1)})
        if segment_limit:                       # If segment limit is set, discard the smaller segments
            segments = sorted(segments, key=len, reverse=True)[:segment_limit]

        # Create bounding box for each segment
        orig_w, orig_h = gray_img.size
        scale_w = orig_w / pre_segment_size
        scale_h = orig_h / pre_segment_size

        hashes = []
        for segment in segments:
            x_vals = {coord[1] for coord in segment}
            bbox = (
                min(x_vals) * scale_w,              # min_x
                min(segment)[0] * scale_h,          # min_y
                (max(x_vals) + 1) * scale_w,        # max_x
                (max(segment)[0] + 1) * scale_h,    # max_y
            )
            # Compute robust hash src_image each bounding box
            hashes.append(hash_cls.from_image(gray_img.crop(bbox), convert=False))  # noqa

        return cls(hashes)

    def difference(self, other: MultiHash, max_distance: float = None, bit_error_rate: float = None) -> float:
        if distances := self._distances(other, max_distance, bit_error_rate):
            matches = len(distances)
            max_distance = matches * len(self.hashes[0])
            match_score = matches - (sum(distances) / max_distance)  # matches - tie_breaker
            return len(self.hashes) - match_score
        else:
            return len(self.hashes)  # max_difference

    __sub__ = difference

    def relative_difference(self, other: MultiHash, max_distance: float = None, bit_error_rate: float = None) -> float:
        # Closer to 0 means fewer differences, closer to 1 means more differences
        return self.difference(other, max_distance, bit_error_rate) / len(self.hashes)

    __or__ = relative_difference

    def matches(
        self,
        other: MultiHash,
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

    def _distances(self, other: MultiHash, max_distance: float = None, bit_error_rate: float = None) -> list[int]:
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
        self, others: Collection[MultiHash], max_distance: float = None, bit_error_rate: float = None
    ) -> list[tuple[float, MultiHash]]:
        return sorted(((self.difference(other, max_distance, bit_error_rate), other) for other in others))


def _find_all_segments(pixels, segment_threshold, min_segment_size) -> list[set[Pixel]]:
    """
    Finds all the regions within an image pixel array, and returns a list of the regions.

    Note: Slightly different segmentations are produced when using pillow version 6 vs. >=7, due to a change in
    rounding in the greyscale conversion.

    :param pixels: A numpy array of the pixel brightnesses.
    :param segment_threshold: The brightness threshold to use when differentiating between hills and valleys.
    :param min_segment_size: The minimum number of pixels for a segment.
    """
    img_width, img_height = pixels.shape
    threshold_pixels = pixels > segment_threshold
    unassigned_pixels = np_full(pixels.shape, True, dtype=bool)

    # Add all the pixels around the border outside the image:
    already_segmented = {(x, z) for x in (-1, img_width) for z in range(img_height)}
    already_segmented.update((z, y) for y in (-1, img_height) for z in range(img_width))

    segments = []
    # Find all the "hill" regions
    while (remaining_pixels := bitwise_and(threshold_pixels, unassigned_pixels)).any():
        segment = _find_region(remaining_pixels, already_segmented)
        # Apply segment
        if len(segment) > min_segment_size:
            segments.append(segment)
        for pix in segment:
            unassigned_pixels[pix] = False

    # Invert the threshold matrix, and find "valleys"
    threshold_pixels_i = np_invert(threshold_pixels)
    img_area = img_width * img_height
    while len(already_segmented) < img_area:
        segment = _find_region(bitwise_and(threshold_pixels_i, unassigned_pixels), already_segmented)
        # Apply segment
        if len(segment) > min_segment_size:
            segments.append(segment)
        for pix in segment:
            unassigned_pixels[pix] = False

    return segments


def _find_region(remaining_pixels, segmented: set[Pixel]) -> set[Pixel]:
    """
    Finds a region and returns a set of pixel coordinates for it.

    :param remaining_pixels: A numpy bool array, with True meaning the pixels are remaining to segment
    :param segmented: A set of pixel coordinates which have already been assigned to segment. This will be
      updated with the new pixels added to the returned segment.
    """
    not_in_region = set()
    start = tuple(transpose(nonzero(remaining_pixels))[0])  # The first pixel in remaining_pixels with a value of True
    in_region = {start}
    new = {start}
    while try_next := {p for x, y in new for p in ((x-1, y), (x+1, y), (x, y-1), (x, y+1))} - segmented - not_in_region:
        # Empty new pixels set, so we know whose neighbour's to check next time
        new = {pixel for pixel in try_next if remaining_pixels[pixel]}
        in_region.update(new)
        segmented.update(new)
        not_in_region.update(try_next - new)
    return in_region


# endregion

# endregion

MULTI_CLS = RotatedMultiHash

# region Tables


class Base(DeclarativeBase):
    pass


class Directory(Base):
    __tablename__ = 'dirs'
    id: Mapped[int] = Column(Integer, primary_key=True)
    path: Mapped[str] = Column(String, index=True, unique=True)


class ImageHash(Base):
    __tablename__ = 'hashes'
    id: Mapped[int] = Column(Integer, primary_key=True)

    a: Mapped[int] = Column(Integer, index=True)  # Actually uint8, but sqlite and sqlalchemy don't support bit widths
    b: Mapped[int] = Column(Integer, index=True)
    c: Mapped[int] = Column(Integer, index=True)
    d: Mapped[int] = Column(Integer, index=True)

    e: Mapped[int] = Column(Integer, index=True)
    f: Mapped[int] = Column(Integer, index=True)
    g: Mapped[int] = Column(Integer, index=True)
    h: Mapped[int] = Column(Integer, index=True)

    image_id: Mapped[int] = Column(Integer, ForeignKey('images.id'))
    image: Mapped[ImageFile] = relationship('ImageFile', back_populates='hashes', lazy='joined')

    @cached_property(block=False)
    def img_hash(self) -> HASH_CLS:
        return HASH_CLS(array([self.a, self.b, self.c, self.d, self.e, self.f, self.g, self.h], dtype=uint8))


class ImageFile(Base):
    __tablename__ = 'images'
    id: Mapped[int] = Column(Integer, primary_key=True)
    name: Mapped[str] = Column(String)
    size: Mapped[int] = Column(Integer)
    mod_time: Mapped[int] = Column(Integer)
    dir_id: Mapped[int] = Column(Integer, ForeignKey('dirs.id'))
    dir: Mapped[Directory] = relationship(Directory, lazy='joined')
    sha256sum: Mapped[str] = Column(String)
    hashes: Mapped[list[ImageHash]] = relationship(
        ImageHash, back_populates='image', cascade='all, delete, delete-orphan', lazy='joined'
    )

    def __repr__(self) -> str:
        return f'<{self.__class__.__name__}({self.name!r})>'

    @property
    def mod_time_dt(self) -> datetime:
        return datetime.fromtimestamp(self.mod_time)

    @property
    def path(self) -> Path:
        return Path(self.dir.path, self.name)

    @cached_property(block=False)
    def multi_hash(self) -> MULTI_CLS:
        return MULTI_CLS([h.img_hash for h in self.hashes])

    def difference(self, *args, **kwargs):
        return self.multi_hash.difference(*args, **kwargs)

    def relative_difference(self, *args, **kwargs):
        return self.multi_hash.relative_difference(*args, **kwargs)


TABLE_MAP = {cls.__tablename__: cls for cls in (Directory, ImageFile, ImageHash)}

# endregion


class ImageDB:
    session: scoped_session

    def __init__(self, path: str | Path, expire_on_commit: bool = False):
        register_adapter(uint8, int)    # Necessary to ensure all hash chunks are stored as integers instead of bytes
        register_adapter(uint16, int)   # Necessary to ensure all hash chunks are stored as integers instead of bytes
        if path != ':memory:':
            path = Path(path).expanduser()
            if not path.parent.exists():
                path.parent.mkdir(parents=True, exist_ok=True)
            path = path.as_posix()

        engine = create_engine(f'sqlite:///{path}')
        Base.metadata.create_all(engine)
        self.session = scoped_session(sessionmaker(bind=engine, expire_on_commit=expire_on_commit))
        self._dir_cache = {}

    def get_dir(self, path: Path) -> Directory:
        dir_str = path.parent.as_posix()
        if dir_obj := self._dir_cache.get(dir_str):
            return dir_obj
        elif dir_obj := self.session.query(Directory).filter_by(path=dir_str).first():
            self._dir_cache[dir_str] = dir_obj
            return dir_obj  # noqa
        dir_obj = Directory(path=dir_str)
        self.session.add(dir_obj)
        self.session.commit()
        self._dir_cache[dir_str] = dir_obj
        return dir_obj

    def add_image(self, path: Path) -> ImageFile:
        return self._add_image(path, MULTI_CLS.from_any(path, HASH_CLS), sha256(path.read_bytes()).hexdigest())

    def add_images(self, paths: Iterable[Path], workers: int = None):
        with ProcessPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(_hash_image, path): path for path in paths}  # noqa
            with tqdm(total=len(futures), unit='img', smoothing=0.1, maxinterval=1) as prog_bar:
                try:
                    for i, future in enumerate(as_completed(futures)):
                        path = futures[future]
                        prog_bar.update(1)
                        try:
                            multi_hash, sha256sum, stat_info = future.result()
                        except Exception as e:
                            exc_info = not isinstance(e, UnidentifiedImageError)
                            log.error(f'Error hashing {path}: {e}', exc_info=exc_info, extra={'color': 'red'})
                        else:
                            image = self._add_image(path, multi_hash, sha256sum, commit=False, stat_info=stat_info)
                            if i % 100 == 0:
                                self.session.commit()
                            log.debug(f'Added {image=}')
                except BaseException:
                    executor.shutdown(cancel_futures=True)
                    raise
                finally:
                    self.session.commit()

    def _add_image(
        self, path: Path, multi_hash: MULTI_CLS, sha256sum: str, commit: bool = True, stat_info: stat_result = None
    ) -> ImageFile:
        if not stat_info:
            stat_info = path.stat()
        image = ImageFile(
            dir=self.get_dir(path),
            name=path.name,
            size=stat_info.st_size,
            mod_time=stat_info.st_mtime,
            sha256sum=sha256sum,
        )
        for seg_hash in multi_hash.hashes:
            a, b, c, d, e, f, g, h = seg_hash.array
            image.hashes.append(ImageHash(a=a, b=b, c=c, d=d, e=e, f=f, g=g, h=h))

        self.session.add(image)
        if commit:
            self.session.commit()
        return image

    def get_image(self, path: Path) -> ImageFile | None:
        return self.session.query(ImageFile).filter_by(name=path.name)\
            .join(Directory).filter_by(path=path.parent.as_posix())\
            .first()

    def find_similar(
        self,
        image: ImageType,
        max_rel_distance: float = 0.05,
        # bit_error_rate: float = 0.2
    ) -> list[tuple[ImageFile, float]]:
        multi_hash = MULTI_CLS.from_any(image, HASH_CLS)
        query = self._find_similar(multi_hash)
        return [
            (img_row, distance)
            for img_row in query.all()
            # if (distance := img_row.relative_difference(multi_hash, bit_error_rate=bit_error_rate)) <= max_rel_distance
            if (distance := img_row.relative_difference(multi_hash)) <= max_rel_distance
        ]

    def _find_similar(self, multi_hash: MULTI_CLS) -> Query:
        a, b, c, d, e, f, g, h = array([h.array for h in multi_hash.hashes]).transpose()
        return self.session.query(ImageFile).join(ImageHash).filter(
            or_(
                ImageHash.a.in_(a), ImageHash.b.in_(b), ImageHash.c.in_(c), ImageHash.d.in_(d),  # noqa
                ImageHash.e.in_(e), ImageHash.f.in_(f), ImageHash.g.in_(g), ImageHash.h.in_(h),  # noqa
            )
        )

    def find_exact_dupes(self) -> Iterator[tuple[str, int, list[ImageFile]]]:
        last_sha, last_num, images = None, 0, []
        for sha, num, image in self._find_exact_dupes():
            if sha != last_sha:
                if images:
                    yield last_sha, last_num, images
                images = [image]
                last_num = num
                last_sha = sha
            else:
                images.append(image)

        if images:
            yield last_sha, last_num, images

    def _find_exact_dupes(self) -> Query:
        sub_query = self.session.query(ImageFile.sha256sum, count(ImageFile.id.distinct()))\
            .group_by(ImageFile.sha256sum).subquery()

        query = self.session.query(ImageFile.sha256sum, sub_query.c.count, ImageFile)\
            .join(sub_query, sub_query.c.sha256sum == ImageFile.sha256sum)\
            .where(sub_query.c.count > 1) \
            .order_by(sub_query.c.count.desc())

        return query

    def _find_similar_dupes(self) -> Query:
        hash_parts = (
            ImageHash.a, ImageHash.b, ImageHash.c, ImageHash.d, ImageHash.e, ImageHash.f, ImageHash.g, ImageHash.h
        )
        # part_queries = [
        #     self.session.query(ImageHash.id, count(ImageHash.image_id.distinct())).group_by(p).subquery()
        #     for p in hash_parts
        # ]

        query = part_query = self.session.query(ImageHash.id, count(ImageHash.image_id.distinct())) \
            .group_by(*hash_parts)
            # .group_by(or_(*hash_parts)).subquery()

        # hash_query = self.session.query(ImageHash.id, part_query.c.count)\
        #     .join(part_query, part_query.c.id == ImageHash.id)\
        #     .where(part_query.c.count > 1).subquery()

        # query = self.session.query(ImageHash, part_query.c.count, ImageFile) \
        #     .join(hash_query, hash_query.c.id == ImageHash.id) \
        #     .join(ImageFile) \
        #     .order_by(part_query.c.count.desc())
        return query


def _hash_image(path: Path) -> tuple[MULTI_CLS, str, stat_result]:
    data = path.read_bytes()
    return MULTI_CLS.from_file(BytesIO(data)), sha256(data).hexdigest(), path.stat()
