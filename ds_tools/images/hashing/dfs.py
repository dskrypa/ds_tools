"""
Storage/query implementation for finding images that are perceptually similar to other known images that uses Pandas
DataFrames.

Significantly faster than the alternative implementation that uses a Sqlite3 DB.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from functools import cached_property
from hashlib import sha256
from pathlib import Path
from typing import TYPE_CHECKING, Collection, Iterable, Iterator, Type

from numpy import uint8, frombuffer, stack
from pandas import DataFrame, concat, read_feather

from .multi import RotatedMultiHash, get_multi_class
from .processing import ImageProcessor
from .single import DifferenceHash, get_hash_class

if TYPE_CHECKING:
    from numpy.typing import NDArray
    from ..typing import ImageType
    from .single import ImageHashBase
    from .multi import MultiHash

__all__ = ['ImageHashes']
log = logging.getLogger(__name__)

HASH_CLS = DifferenceHash
MULTI_CLS = RotatedMultiHash
DEFAULT_HASH_MODE = HASH_CLS.mode
DEFAULT_MULTI_MODE = MULTI_CLS.mode


class ImageHashes:
    hash_cls: Type[ImageHashBase]
    multi_cls: Type[MultiHash]
    _meta_df: DataFrame | None
    _hash_df: DataFrame | None

    def __init__(
        self,
        meta_path: str | Path | None = None,
        hash_path: str | Path | None = None,
        *,
        hash_mode: str = DEFAULT_HASH_MODE,
        multi_mode: str = DEFAULT_MULTI_MODE,
        cache_dir: Path | str = '~/.cache/img_hash_db',
    ):
        global HASH_CLS, MULTI_CLS
        self.hash_cls = HASH_CLS = get_hash_class(hash_mode)
        self.multi_cls = MULTI_CLS = get_multi_class(multi_mode)

        cache_dir = Path(cache_dir).expanduser()
        if meta_path is None:
            self.meta_path = cache_dir.joinpath('image_metadata.feather')
        else:
            self.meta_path = Path(meta_path).expanduser()

        if hash_path is None:
            self.hash_path = cache_dir.joinpath(f'{self.multi_cls.__name__}_{self.hash_cls.__name__}_hashes.feather')
        else:
            self.hash_path = Path(hash_path).expanduser()

        self.meta_path.parent.mkdir(parents=True, exist_ok=True)
        self.hash_path.parent.mkdir(parents=True, exist_ok=True)

    @cached_property
    def _meta_df(self) -> DataFrame | None:
        return _maybe_read_df(self.meta_path)

    @cached_property
    def _hash_df(self) -> DataFrame | None:
        return _maybe_read_df(self.hash_path)

    @property
    def meta_df(self) -> DataFrame:
        self._ensure_initialized('access metadata')
        return self._meta_df

    @property
    def hash_df(self) -> DataFrame:
        self._ensure_initialized('access hashes')
        return self._hash_df

    def save(self):
        if self._meta_df is None:
            log.warning('Attempted save, but there is no data to save')
            return

        log.debug(f'Saving {self.meta_path.as_posix()}')
        with self.meta_path.open('wb') as f:
            self._meta_df.to_feather(f)

        log.debug(f'Saving {self.hash_path.as_posix()}')
        with self.hash_path.open('wb') as f:
            self._hash_df.to_feather(f)

    def _ensure_initialized(self, purpose: str):
        if self._hash_df is None:
            raise ImageHashError(f'Unable to {purpose} - hash DataFrame not initialized (no images were scanned yet)')

    def _add_meta(self, meta_df: DataFrame):
        try:
            # Unless separate synced lists are used to store paths / data, there doesn't seem to be any way to
            # initialize the df with this as the index.
            meta_df.set_index('path', inplace=True)
        except KeyError:
            pass  # The correct / expected index is already set

        if self._meta_df is not None:
            self._meta_df = concat([self._meta_df, meta_df])
        else:
            self._meta_df = meta_df

    def _add_hashes(self, hash_df: DataFrame):
        if self._hash_df is not None:
            self._hash_df = concat([self._hash_df, hash_df])
        else:
            self._hash_df = hash_df

    def add_image(self, path: Path):
        stat = path.stat()
        multi_hash = self.multi_cls.from_any(path, hash_cls=self.hash_cls)
        path_str = path.as_posix()
        meta_row = {'size': stat.st_size, 'mod_time': stat.st_mtime, 'sha256sum': sha256(path.read_bytes()).hexdigest()}
        self._add_meta(DataFrame(meta_row, index=[path_str]))
        self._add_hashes(DataFrame({'path': path_str, 'hash': [h.array for h in multi_hash.hashes]}))

    def add_images(
        self,
        paths: Iterable[Path],
        *,
        workers: int | None = None,
        skip_hashed: bool = True,
        use_executor: bool = False,
    ):
        paths = self._prep_paths(paths, skip_hashed)
        processor = ImageProcessor(workers, self.hash_cls.mode, self.multi_cls.mode, use_executor=use_executor)

        meta_rows = []
        hash_rows = []
        for i, path, (hashes, sha256sum, size, mod_time) in processor.process_images(paths):
            path_str = path.as_posix()
            meta_rows.append({'path': path_str, 'size': size, 'mod_time': mod_time, 'sha256sum': sha256sum})
            hash_rows.extend({'path': path_str, 'hash': frombuffer(h, dtype=uint8)} for h in hashes)

        self._add_meta(DataFrame(meta_rows))
        self._add_hashes(DataFrame(hash_rows))

    def _prep_paths(self, paths: Iterable[Path], skip_hashed: bool = True) -> Collection[Path]:
        if skip_hashed:
            hashed = self._get_all_paths()
            log.debug(f'Filtering the provided paths to ignore {len(hashed):,d} paths that were already hashed')
            return [path for path in paths if path not in hashed]

        try:
            len(paths)  # noqa
        except Exception:  # noqa
            return list(paths)
        else:
            return paths  # noqa

    def _get_all_paths(self) -> set[Path]:
        if self._meta_df is None:
            return set()
        else:
            # return set(map(Path, self._meta_df['path'].values))
            return set(map(Path, self._meta_df.index))

    def get_image(self, path: Path | str) -> ImageFile | None:
        self._ensure_initialized('get image')
        if isinstance(path, Path):
            path = path.as_posix()
        return self._get_image(path, self._hash_df[self._hash_df['path'] == path]['hash'].values)

    def find_similar(self, image: ImageType, max_rel_distance: float = 0.05) -> list[tuple[ImageFile, float]]:
        multi_hash = self.multi_cls.from_any(image, hash_cls=self.hash_cls)
        images = (
            self._get_image(path, list(group['hash']))  # noqa
            for path, group in self._find_similar(multi_hash).groupby('path')
        )
        return [(img, dist) for img in images if (dist := img.relative_difference(multi_hash)) <= max_rel_distance]

    def _find_similar(self, multi_hash: MultiHash, min_matches: int = 2) -> DataFrame:
        self._ensure_initialized('find similar images')
        df_hashes = stack(self._hash_df['hash'])
        hash_arrays = (h.array for h in multi_hash.hashes)
        # Given 1D arrays a = [1, 2, 3], b = [1, 4, 5], c = [2, 1, 4]; (a == b).any() is True, but (a == c).any() is
        # False.  The same positional behavior applies to `.sum()`, which lets us count the number of matching parts.
        # Given the 2D df_hashes array and 1D `arr` arrays representing the 8 hash parts,
        # `(df_hashes == arr).sum(axis=1)` provides a mask for the 2D array based on the sum of matching positional
        # values in each row.  That is then filtered with `>= min_matches` to only the rows where at least that number
        # of positional hash parts match.  Masks for each hash in the given multi hash are combined so that rows that
        # match any of those hashes are returned.
        mask = (df_hashes == next(hash_arrays)).sum(axis=1) >= min_matches  # noqa
        for arr in hash_arrays:
            mask |= (df_hashes == arr).sum(axis=1) >= min_matches  # noqa  # PyCharm assumes non-numpy == behavior

        return self._hash_df[mask]

    def _get_hashes(self, path: str) -> list[ImageHashBase]:
        hash_arrays = self._hash_df[self._hash_df['path'] == path]['hash'].values
        return [self.hash_cls(a) for a in hash_arrays]

    def _get_image(self, path: str, hash_arrays: list[NDArray]) -> ImageFile:
        meta = self._meta_df.loc[path]
        return ImageFile(
            path=Path(path),
            size=meta['size'],
            mod_time=meta['mod_time'],
            sha256sum=meta['sha256sum'],
            hashes=[self.hash_cls(a) for a in hash_arrays],
        )

    def find_exact_dupes(self) -> Iterator[tuple[str, int, list[ImageFile]]]:
        self._ensure_initialized('find exact dupes')
        for sha256sum, group in self._meta_df[self._meta_df.duplicated('sha256sum', keep=False)].groupby('sha256sum'):
            images = [
                ImageFile(Path(path), size, mod_time, img_sha, self._get_hashes(path))
                for path, size, mod_time, img_sha in group.itertuples(name=None)
            ]
            yield sha256sum, len(images), images


@dataclass
class ImageFile:
    path: Path
    size: int
    mod_time: float
    sha256sum: str
    hashes: list[ImageHashBase]

    def __repr__(self) -> str:
        return f'<{self.__class__.__name__}({self.name!r})>'

    @property
    def mod_time_dt(self) -> datetime:
        return datetime.fromtimestamp(self.mod_time)

    @property
    def name(self) -> str:
        return self.path.name

    @cached_property
    def multi_hash(self) -> MultiHash:
        return MULTI_CLS(self.hashes)

    def difference(self, *args, **kwargs):
        return self.multi_hash.difference(*args, **kwargs)

    def relative_difference(self, *args, **kwargs):
        return self.multi_hash.relative_difference(*args, **kwargs)


def _maybe_read_df(path: Path | str) -> DataFrame | None:
    try:
        with open(path, 'rb') as f:
            return read_feather(f)
    except FileNotFoundError:
        return None


class ImageHashError(Exception):
    pass
