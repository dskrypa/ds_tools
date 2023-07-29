#!/usr/bin/env python

from pathlib import Path

from cli_command_parser import Command, SubCommand, Positional, Option, Flag, Counter, main
from cli_command_parser.inputs import Path as IPath, NumRange

from ds_tools.__version__ import __author_email__, __version__  # noqa
from ds_tools.caching.decorators import cached_property
from ds_tools.images.hashing import ImageDB, Directory, ImageHash, ImageFile

PCT_FLOAT = NumRange(float, min=0, max=1, include_max=True)


class ImageDBCLI(Command, description='Image Hash DB CLI', option_name_mode='*-'):
    action = SubCommand()
    verbose = Counter('-v', help='Increase logging verbosity (can specify multiple times)')
    db_path: Path = Option(
        '-db', type=IPath(type='file'), default='~/.cache/img_hash_db/img_hashes.db', help='Path to the DB that should be used'
    )

    def _init_command_(self):
        from ds_tools.logging import init_logging

        init_logging(self.verbose, log_path=None)

    @cached_property
    def image_db(self) -> ImageDB:
        return ImageDB(self.db_path)


class Status(ImageDBCLI, help='Show info about the DB'):
    def main(self):
        print(f'DB location: {self.db_path.as_posix()}')
        tables = {'directories': Directory, 'images': ImageFile, 'hashes': ImageHash}
        for name, table_cls in tables.items():
            row_count = self.image_db.session.query(table_cls).count()
            print(f'Saved {name}: {row_count:,d}')


class Scan(ImageDBCLI, help='Scan images to populate the DB'):
    paths = Positional(nargs='+', help='One or more image files to hash and store in the DB')
    no_ext_filter = Flag(help='Do not filter files by extension')
    max_workers: int = Option('-w', help='Maximum number of worker processes to use (default: based on core count)')

    def main(self):
        from ds_tools.fs.paths import iter_files

        path_iter = iter_files(self.paths)
        if not self.no_ext_filter:
            ext_allow_list = {'.jpg', '.jpeg', '.png'}
            path_iter = (p for p in path_iter if p.suffix.lower() in ext_allow_list)

        self.image_db.add_images(path_iter, self.max_workers)


class Find(ImageDBCLI, help='Find images in the DB similar to the given image'):
    path: Path = Positional(type=IPath(type='file', exists=True), help='An image file')
    max_distance = Option('-D', default=0.05, type=PCT_FLOAT, help='Max distance as a % of hash bits that differ')

    def main(self):
        if rows := self.image_db.find_similar(self.path, max_rel_distance=self.max_distance):
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
        for sha, num, images in self.image_db.find_exact_dupes():
            print(f'{sha}: {len(images)}:\n' + '\n'.join(sorted(f' - {img.path.as_posix()}' for img in images)))

    def print_filtered_dupes(self):
        dirs = {Path(path).expanduser() for path in self.dir_filter}
        for sha, num, images in self.image_db.find_exact_dupes():
            if not any(img.path.parent in dirs for img in images):
                continue
            print(f'{sha}: {len(images)}:\n' + '\n'.join(sorted(f' - {img.path.as_posix()}' for img in images)))


class Similar(ImageDBCLI, help='Find similar images in the DB'):
    def main(self):
        pass
        # query = self.image_db._find_similar_dupes()
        # print(query)
        # results = query.all()
        # print(f'Found {len(results)} results')
        # print(results[0])


if __name__ == '__main__':
    main()
