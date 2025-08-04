from __future__ import annotations

import logging
from datetime import datetime
from functools import cached_property
from hashlib import sha256
from math import log10
from pathlib import Path
from sqlite3 import register_adapter
from struct import Struct
from typing import TYPE_CHECKING, Any, Collection, Iterable, Iterator, Type

from numpy import array, uint8
from sqlalchemy import create_engine, Column, Integer, String, ForeignKey, or_
from sqlalchemy.sql.functions import count
from sqlalchemy.orm import Query, relationship, scoped_session, sessionmaker, DeclarativeBase, Mapped

from .multi import RotatedMultiHash, get_multi_class
from .processing import process_images, process_images_mp, process_images_via_executor
from .single import DifferenceHash, get_hash_class

if TYPE_CHECKING:
    from ..typing import ImageType
    from .single import ImageHashBase
    from .multi import MultiHash

__all__ = ['ImageDB', 'DEFAULT_HASH_MODE', 'DEFAULT_MULTI_MODE']
log = logging.getLogger(__name__)

HASH_CLS = DifferenceHash
MULTI_CLS = RotatedMultiHash
DEFAULT_HASH_MODE = HASH_CLS.mode
DEFAULT_MULTI_MODE = MULTI_CLS.mode


class ImageDB:
    session: scoped_session
    hash_cls: Type[ImageHashBase]
    multi_cls: Type[MultiHash]

    def __init__(
        self,
        path: str | Path,
        *,
        hash_mode: str = DEFAULT_HASH_MODE,
        multi_mode: str = DEFAULT_MULTI_MODE,
        expire_on_commit: bool = False,
    ):
        global HASH_CLS, MULTI_CLS
        self.hash_cls = HASH_CLS = get_hash_class(hash_mode)
        self.multi_cls = MULTI_CLS = get_multi_class(multi_mode)

        register_adapter(uint8, int)    # Necessary to ensure all hash chunks are stored as integers instead of bytes
        if path != ':memory:':
            path = Path(path).expanduser()
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

        self._dir_cache[dir_str] = dir_obj = Directory(path=dir_str)
        self.session.add(dir_obj)
        self.session.commit()
        return dir_obj

    def add_image(self, path: Path) -> ImageFile:
        stat_info = path.stat()
        multi_hash = self.multi_cls.from_any(path, hash_cls=self.hash_cls)
        image = ImageFile(
            dir=self.get_dir(path),
            name=path.name,
            size=stat_info.st_size,
            mod_time=stat_info.st_mtime,
            sha256sum=sha256(path.read_bytes()).hexdigest(),
            hashes=[ImageHash(**dict(zip('abcdefgh', seg_hash.array))) for seg_hash in multi_hash.hashes],
        )
        self.session.add(image)
        self.session.commit()
        return image

    def add_images(
        self,
        paths: Iterable[Path],
        *,
        workers: int | None = None,
        skip_hashed: bool = True,
        use_executor: bool = False,
    ):
        paths = self._prep_paths(paths, skip_hashed)
        self._prep_dir_cache(paths)

        commit_freq = max(100, 10 ** (int(log10(len(paths))) - 1) // 2)
        log.debug(f'Using {commit_freq=}')

        kwargs: dict[str, Any] = {'hash_mode': self.hash_cls.mode, 'multi_mode': self.multi_cls.mode}
        if workers is None or workers > 1:
            # Even after optimizing away some of the serialization/deserialization overhead, after a certain point, a
            # CPU usage pattern emerges where there are periods of high/efficient CPU use followed by long periods of
            # relative inactivity.
            # The root cause is that it takes significantly longer to deserialize all results / insert them in the DB
            # than it takes to process all of them.  This can be observed by having worker processes print when they
            # finish, yet observing via the progress bar that thousands of results are still pending processing.
            process_images_func = process_images_via_executor if use_executor else process_images_mp
            kwargs['workers'] = workers
        else:
            process_images_func = process_images

        unpack = Struct('8B').unpack
        for i, path, (hashes, sha256sum, size, mod_time) in process_images_func(paths, **kwargs):
            image = ImageFile(
                dir=self._dir_cache[path.parent.as_posix()],
                name=path.name,
                size=size,
                mod_time=mod_time,
                sha256sum=sha256sum,
                # Struct.unpack is ~2x faster than `numpy.frombuffer` for this, and providing the kwarg values this way
                # is ~2x faster than ** expansion of `dict(zip('abcdefgh', arr))`.
                hashes=[
                    ImageHash(a=a[0], b=a[1], c=a[2], d=a[3], e=a[4], f=a[5], g=a[6], h=a[7])
                    for a in map(unpack, hashes)
                ],
            )
            # Note: `session.add_all` ends up calling `session.add` in a loop, so doesn't appear that it would help
            self.session.add(image)
            # log.debug(f'Added {image=}')
            if i % commit_freq == 0:
                self.session.commit()

        self.session.commit()

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

    def _prep_dir_cache(self, paths: Collection[Path]):
        """
        Pre-populating Directory entries prevents potentially frequent extra commits while processing image results.
        """
        self._dir_cache = {d.path: d for d in self.session.query(Directory).all()}
        added = False
        for dir_str in {path.parent.as_posix() for path in paths}:
            if dir_str not in self._dir_cache:
                self._dir_cache[dir_str] = dir_obj = Directory(path=dir_str)  # noqa
                self.session.add(dir_obj)
                added = True

        if added:
            self.session.commit()

    def get_image(self, path: Path) -> ImageFile | None:
        return self.session.query(ImageFile).filter_by(name=path.name)\
            .join(Directory).filter_by(path=path.parent.as_posix())\
            .first()

    def _get_all_paths(self) -> set[Path]:
        # This is faster than querying all ImageFiles, which seems to more eagerly load entities
        dirs = {d.id: d.path for d in self.session.query(Directory).all()}
        return {
            Path(dirs[f.dir_id], f.name) for f in self.session.query(ImageFile.name, ImageFile.dir_id).all()  # noqa
        }

    def find_similar(
        self,
        image: ImageType,
        max_rel_distance: float = 0.05,
        # bit_error_rate: float = 0.2
    ) -> list[tuple[ImageFile, float]]:
        multi_hash = self.multi_cls.from_any(image, hash_cls=self.hash_cls)
        query = self._find_similar(multi_hash)
        return [
            (img_row, distance)
            for img_row in query.all()
            # if (distance := img_row.relative_difference(multi_hash, bit_error_rate=bit_error_rate)) <= max_rel_distance
            if (distance := img_row.relative_difference(multi_hash)) <= max_rel_distance
        ]

    def _find_similar(self, multi_hash: MultiHash) -> Query:
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

        # noinspection PyTypeChecker
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

    @cached_property
    def img_hash(self) -> ImageHashBase:
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

    @cached_property
    def multi_hash(self) -> MultiHash:
        return MULTI_CLS([h.img_hash for h in self.hashes])

    def difference(self, *args, **kwargs):
        return self.multi_hash.difference(*args, **kwargs)

    def relative_difference(self, *args, **kwargs):
        return self.multi_hash.relative_difference(*args, **kwargs)


TABLE_MAP = {cls.__tablename__: cls for cls in (Directory, ImageFile, ImageHash)}

# endregion
