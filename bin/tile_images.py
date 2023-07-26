#!/usr/bin/env python

from pathlib import Path

from cli_command_parser import Command, Option, Flag, Counter, Positional, ParamGroup, main
from cli_command_parser.inputs import Path as IPath, NumRange

from ds_tools.__version__ import __author_email__, __version__  # noqa
from ds_tools.caching.decorators import cached_property


class TileImages(Command, description='Tile Images', option_name_mode='*-'):
    in_paths = Positional(nargs='+', help='One or more image files or directories containing image files to include')
    out_path: Path = Option('-o', required=True, type=IPath(type='file', exists=False), help='Output file path')

    with ParamGroup('Layout', mutually_dependent=True):
        rows: int = Option('-r', type=NumRange(min=1), help='Number of images to use along the Y axis')
        columns: int = Option('-c', type=NumRange(min=1), help='Number of images to use along the X axis')

    with ParamGroup('Dimension', mutually_dependent=True):
        width: int = Option('-W', type=NumRange(min=1), default=8000, help='Output image width in pixels')
        height: int = Option('-H', type=NumRange(min=1), default=8000, help='Output image height in pixels')

    verbose = Counter('-v', help='Increase logging verbosity (can specify multiple times)')
    dry_run = Flag('-D', help='Print the actions that would be taken instead of taking them')

    def _init_command_(self):
        from ds_tools.logging import init_logging

        init_logging(self.verbose, log_path=None)

    @cached_property
    def _in_paths(self) -> list[Path]:
        from random import shuffle
        from ds_tools.fs.paths import iter_files

        ext_allow_list = {'.jpg', '.jpeg', '.png'}
        paths = [path for path in iter_files(self.in_paths) if path.suffix.lower() in ext_allow_list]
        shuffle(paths)
        return paths

    @cached_property
    def rows_and_cols(self) -> tuple[int, int]:
        from math import sqrt

        rows, columns = self.rows, self.columns
        if rows:
            total = rows * columns
            if total > len(self._in_paths):
                raise ValueError(
                    f'Invalid {rows=}, {columns=} combo - it would require {total:,d}'
                    f' images, but only {len(self._in_paths):,d} images were provided'
                )
        else:
            rows = columns = int(sqrt(len(self._in_paths)))

        return rows, columns

    def main(self):
        from PIL.Image import open as open_image, new as new_image

        path_grid = self.get_path_grid()

        if not self.out_path.parent.exists():
            self.out_path.parent.mkdir(parents=True, exist_ok=True)

        rows, columns = self.rows_and_cols
        tile_width, tile_height = tile_size = self.width // rows, self.height // columns

        image = new_image('RGB', (self.width, self.height))
        y = 0
        for r, row in enumerate(path_grid):
            x = 0
            for c, path in enumerate(row):
                in_img = open_image(path).convert('RGB').resize(tile_size)
                image.paste(in_img, (x, y))
                x += tile_width
            y += tile_height

        fmt = 'png' if self.out_path.suffix.lower() == '.png' else 'jpeg'
        print(f'Saving {self.out_path.as_posix()}')
        with self.out_path.open('wb') as f:
            image.save(f, fmt)

    def get_path_grid(self) -> list[list[Path]]:
        rows, columns = self.rows_and_cols
        iter_paths = iter(self._in_paths)
        return [[next(iter_paths) for _ in range(columns)] for _ in range(rows)]


if __name__ == '__main__':
    main()
