from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from functools import cached_property
from hashlib import sha256
from pathlib import Path
from typing import TYPE_CHECKING, Any, Collection, Iterable, Iterator, Type

from numpy import uint8, frombuffer, stack
from pandas import DataFrame, concat, read_feather

from .multi import RotatedMultiHash, get_multi_class
from .processing import process_images, process_images_mp, process_images_via_executor
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
    ):
        global HASH_CLS, MULTI_CLS
        self.hash_cls = HASH_CLS = get_hash_class(hash_mode)
        self.multi_cls = MULTI_CLS = get_multi_class(multi_mode)

        cache_dir = Path('~/.cache/img_hash_db').expanduser()
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

    def _add_meta(self, meta_data: DataFrame | dict[str, str | int | float]):
        if self._meta_df is not None:
            if isinstance(meta_data, dict):
                self._meta_df[len(self._meta_df)] = meta_data  # TODO: Test this
            else:
                meta_data.set_index('path', inplace=True)
                self._meta_df = concat([self._meta_df, meta_data])
        else:
            if isinstance(meta_data, dict):
                self._meta_df = DataFrame([meta_data])
            else:
                self._meta_df = meta_data

            self._meta_df.set_index('path', inplace=True)

    def _add_hashes(self, hash_df: DataFrame):
        if self._hash_df is not None:
            self._hash_df = concat([self._hash_df, hash_df])
        else:
            self._hash_df = hash_df

    def _ensure_initialized(self, purpose: str):
        if self._hash_df is None:
            raise ImageHashError(f'Unable to {purpose} - hash DataFrame not initialized (no images were scanned yet)')

    def add_image(self, path: Path):
        stat_info = path.stat()
        multi_hash = self.multi_cls.from_any(path, hash_cls=self.hash_cls)
        path_str = path.as_posix()
        meta_row = {
            'path': path_str,
            'size': stat_info.st_size,
            'mod_time': stat_info.st_mtime,
            'sha256sum': sha256(path.read_bytes()).hexdigest(),
        }
        self._add_meta(meta_row)
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

        kwargs: dict[str, Any] = {'hash_mode': self.hash_cls.mode, 'multi_mode': self.multi_cls.mode}
        if workers is None or workers > 1:
            process_images_func = process_images_via_executor if use_executor else process_images_mp
            kwargs['workers'] = workers
        else:
            process_images_func = process_images

        meta_rows = []
        hash_rows = []
        for i, path, (hashes, sha256sum, size, mod_time) in process_images_func(paths, **kwargs):
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
        path_arr_map = defaultdict(list)
        for path, hash_array in self._find_similar(multi_hash).itertuples(False, None):
            path_arr_map[path].append(hash_array)

        images = (self._get_image(path, hash_arrays) for path, hash_arrays in path_arr_map.items())
        return [(img, dist) for img in images if (dist := img.relative_difference(multi_hash)) <= max_rel_distance]

    def _find_similar(self, multi_hash: MultiHash, min_matches: int = 2) -> DataFrame:
        self._ensure_initialized('find similar images')
        df_hashes = stack(self._hash_df['hash'].to_numpy())
        hash_arrays = (h.array for h in multi_hash.hashes)
        mask = (df_hashes == next(hash_arrays)).sum(axis=1) >= min_matches  # noqa
        for arr in hash_arrays:
            mask |= (df_hashes == arr).sum(axis=1) >= min_matches  # noqa

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
        df = self._meta_df.groupby('sha256sum').filter(lambda x: len(x) > 1).sort_values(['sha256sum', 'path'])
        last_sha, images = None, []
        for path, size, mod_time, sha256sum in df.itertuples(name=None):
            if sha256sum != last_sha:
                if images:
                    yield last_sha, len(images), images

                images = [ImageFile(Path(path), size, mod_time, sha256sum, self._get_hashes(path))]
                last_sha = sha256sum
            else:
                images.append(ImageFile(Path(path), size, mod_time, sha256sum, self._get_hashes(path)))

        if images:
            yield last_sha, len(images), images


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
