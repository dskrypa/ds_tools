#!/usr/bin/env python

import logging
from multiprocessing import set_start_method
from pathlib import Path

from cli_command_parser import Command, SubCommand, Positional, Option, Flag, Counter, ParamGroup, main
from cli_command_parser.inputs import Path as IPath, NumRange

from ds_tools.caching.decorators import cached_property
from ds_tools.images.hashing import HASH_MODES, MULTI_MODES, get_hash_class, get_multi_class
from ds_tools.images.hashing.db import ImageDB, Directory, ImageHash, ImageFile, DEFAULT_HASH_MODE, DEFAULT_MULTI_MODE
from ds_tools.images.hashing.dfs import ImageHashes

log = logging.getLogger(__name__)

PCT_FLOAT = NumRange(float, min=0, max=1, include_max=True)
CACHE_DIR = '~/.cache/img_hash_db'


class ImageDBCLI(Command, description='Image Hash DB CLI', option_name_mode='*-'):
    action = SubCommand()
    verbose = Counter('-v', help='Increase logging verbosity (can specify multiple times)')
    hash_mode = Option('-m', default=DEFAULT_HASH_MODE, choices=HASH_MODES, help='Use a specific hash mode')
    multi_mode = Option('-M', default=DEFAULT_MULTI_MODE, choices=MULTI_MODES, help='Use a specific multi-hash mode')
    backend = Option(choices=('sqlite3', 'pandas'), default='pandas', help='Which storage/query backend should be used')
    cache_dir: Path = Option(default=CACHE_DIR, type=IPath(type='dir'), help='Base DB/DF storage directory')
    db_path: Path = Option(
        '-db', type=IPath(type='file'), help='Path to the DB that should be used (ignored for --backend=pandas)'
    )

    def _init_command_(self):
        from ds_tools.logging import init_logging

        init_logging(self.verbose, log_path=None)
        set_start_method('spawn')
        log.debug(f'Using storage backend={self.backend}')

    @db_path.register_default_cb  # noqa
    def _db_path(self) -> Path:
        hash_cls = get_hash_class(self.hash_mode)
        multi_cls = get_multi_class(self.multi_mode)
        return self.cache_dir.joinpath(f'{multi_cls.__name__}_{hash_cls.__name__}_hashes.db')

    @cached_property
    def use_pandas(self) -> bool:
        return self.backend == 'pandas'

    @cached_property
    def image_db(self) -> ImageDB:
        return ImageDB(self.db_path, hash_mode=self.hash_mode, multi_mode=self.multi_mode)

    @cached_property
    def image_hashes(self) -> ImageHashes:
        return ImageHashes(hash_mode=self.hash_mode, multi_mode=self.multi_mode, cache_dir=self.cache_dir)


class Status(ImageDBCLI, help='Show info about the DB'):
    def main(self):
        if self.use_pandas:
            self._show_pd_status()
        else:
            self._show_db_status()

    def _show_db_status(self):
        print(f'DB location: {self.db_path.as_posix()}')
        tables = {'directories': Directory, 'images': ImageFile, 'hashes': ImageHash}
        for name, table_cls in tables.items():
            row_count = self.image_db.session.query(table_cls).count()
            print(f'Saved {name}: {row_count:,d}')

    def _show_pd_status(self):
        from ds_tools.output.formatting import readable_bytes

        ih = self.image_hashes
        print(f'Metadata location: {ih.meta_path.as_posix()} ({readable_bytes(ih.meta_path.stat().st_size)})')
        print(f'Hashes location: {ih.hash_path.as_posix()} ({readable_bytes(ih.hash_path.stat().st_size)})')
        print(f'Saved images: {ih.meta_df.shape[0]:,d}')
        print(f'Saved hashes: {ih.hash_df.shape[0]:,d}')


class Reset(ImageDBCLI, help='Reset the DB'):
    def main(self):
        if self.use_pandas:
            paths = (self.image_hashes.meta_path, self.image_hashes.hash_path)
        else:
            paths = (self.db_path,)

        for path in paths:
            log.info(f'Deleting {path.as_posix()}')
            try:
                path.unlink()
            except OSError as e:
                log.error(f'Error deleting {path.as_posix()}: {e}')


class Scan(ImageDBCLI, help='Scan images to populate the DB'):
    paths = Positional(nargs='+', help='One or more image files to hash and store in the DB')

    with ParamGroup('Filter', mutually_exclusive=True):
        no_ext_filter = Flag(help='Do not filter files by extension')
        ext_filter = Option('-f', nargs='+', help='Only process files with the specified extensions')

    max_workers: int = Option('-w', help='Maximum number of worker processes to use (default: based on core count)')

    def main(self):
        from ds_tools.fs.paths import iter_files

        if self.no_ext_filter:
            path_iter = iter_files(self.paths)
        else:
            path_iter = self._iter_paths()

        if self.use_pandas:
            self.image_hashes.add_images(path_iter, workers=self.max_workers)
            self.image_hashes.save()
        else:
            self.image_db.add_images(path_iter, workers=self.max_workers)

    def _iter_paths(self):
        from ds_tools.fs.paths import iter_files

        if self.ext_filter:
            ext_allow_list = {ext if ext.startswith('.') else f'.{ext}' for ext in map(str.lower, self.ext_filter)}  # noqa
        else:
            ext_allow_list = {'.jpg', '.jpeg', '.png'}

        itx = ext_allow_list.intersection
        for path in iter_files(self.paths):
            suffixes = set(map(str.lower, path.suffixes))  # noqa
            if itx(suffixes) and '.errors' not in suffixes:
                yield path


class Find(ImageDBCLI, help='Find images in the DB similar to the given image'):
    path: Path = Positional(type=IPath(type='file', exists=True), help='An image file')
    max_distance = Option('-D', default=0.05, type=PCT_FLOAT, help='Max distance as a % of hash bits that differ')

    def main(self):
        src = self.image_hashes if self.use_pandas else self.image_db
        if rows := src.find_similar(self.path, max_rel_distance=self.max_distance):
            print(f'Found {len(rows)} matches:')
            self.print_table(rows)
        else:
            print(f'No matches found for {self.path.as_posix()}')

    def print_table(self, data: list[tuple[ImageFile, float]]):
        from ds_tools.output.formatting import readable_bytes
        from ds_tools.output.table import Table, SimpleColumn

        rows = [
            {
                'Difference': distance,
                'Path': image.path.as_posix(),
                'Size': readable_bytes(image.size),
                'Last Modified': image.mod_time_dt.isoformat(' ', timespec='seconds'),
            }
            for image, distance in data
        ]

        table = Table(
            SimpleColumn('Difference', ftype='.6f'),
            SimpleColumn('Size'),
            SimpleColumn('Last Modified'),
            SimpleColumn('Path'),
            sort_by=('Difference', 'Path'),
            update_width=True,
        )
        table.print_rows(rows)


class Dupes(ImageDBCLI, help='Find exact duplicate images in the DB'):
    dir_filter = Option('-d', nargs='+', help='If specified, filter results to those in the specified directories')

    def main(self):
        if self.dir_filter:
            self.print_filtered_dupes()
        else:
            self.print_all_exact_dupes()

    def print_all_exact_dupes(self):
        src = self.image_hashes if self.use_pandas else self.image_db
        for sha, num, images in src.find_exact_dupes():
            print(f'{sha}: {len(images)}:\n' + '\n'.join(sorted(f' - {img.path.as_posix()}' for img in images)))

    def print_filtered_dupes(self):
        src = self.image_hashes if self.use_pandas else self.image_db
        dirs = tuple({Path(path).expanduser().as_posix() for path in self.dir_filter})
        for sha, num, images in src.find_exact_dupes():
            if not any(img.path.as_posix().startswith(dirs) for img in images):
                continue
            print(f'{sha}: {len(images)}:\n' + '\n'.join(sorted(f' - {img.path.as_posix()}' for img in images)))


# class Similar(ImageDBCLI, help='Find similar images in the DB'):
#     def main(self):
#         pass
#         # query = self.image_db._find_similar_dupes()
#         # print(query)
#         # results = query.all()
#         # print(f'Found {len(results)} results')
#         # print(results[0])


if __name__ == '__main__':
    main()
