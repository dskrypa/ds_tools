#!/usr/bin/env python

import logging
from pathlib import Path

from cli_command_parser import Command, Option, Flag, Counter, Positional, ParamGroup, main
from cli_command_parser.inputs import Path as IPath, NumRange

from ds_tools.__version__ import __author_email__, __version__  # noqa
from ds_tools.caching.decorators import cached_property

log = logging.getLogger(__name__)


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

    def main(self):
        from PIL.Image import new as new_image

        if not self.out_path.parent.exists():
            self.out_path.parent.mkdir(parents=True, exist_ok=True)

        width, height = self.width, self.height
        cols, rows = self.cols_and_rows
        tile_width, tile_height = self.tile_size

        prefix = '[DRY RUN] Would create' if self.dry_run else 'Creating'
        log.info(
            f'{prefix} a {width} x {height} px composite image with {tile_width} x {tile_height} px tiles'
            f' in a {cols} x {rows} grid, using {cols * rows:,d} / {len(self._in_paths):,d} images'
        )
        if self.dry_run:
            return

        image = new_image('RGB', (width, height))
        for tile, box in self.iter_tiles():
            image.paste(tile, box)

        fmt = 'png' if self.out_path.suffix.lower() == '.png' else 'jpeg'
        log.info(f'Saving {self.out_path.as_posix()}')
        with self.out_path.open('wb') as f:
            image.save(f, fmt)

    @cached_property
    def _in_paths(self) -> list[Path]:
        from random import shuffle
        from ds_tools.fs.paths import iter_files

        ext_allow_list = {'.jpg', '.jpeg', '.png'}
        paths = [path for path in iter_files(self.in_paths) if path.suffix.lower() in ext_allow_list]
        shuffle(paths)
        return paths

    @cached_property
    def cols_and_rows(self) -> tuple[int, int]:
        cols, rows = self.columns, self.rows
        img_count = len(self._in_paths)
        if cols:  # They are mutually dependent
            total = cols * rows
            if total > img_count:
                raise ValueError(
                    f'Invalid {cols=}, {rows=} combo - it would require {total:,d}'
                    f' images, but only {img_count:,d} images were provided'
                )
        elif self.width == self.height:
            cols = rows = int(img_count ** 0.5)
        else:
            aspect_ratio = self.width / self.height
            rows = int((img_count / aspect_ratio) ** 0.5)
            cols = img_count // rows

        return cols, rows

    @cached_property
    def tile_size(self) -> tuple[int, int]:
        cols, rows = self.cols_and_rows
        return self.width // cols, self.height // rows

    def iter_tiles(self):
        from PIL.Image import open as open_image

        cols, rows = self.cols_and_rows
        tile_width, tile_height = tile_size = self.tile_size

        paths = iter(self._in_paths)
        for row in range(rows):  # y
            y = row * tile_height
            for col in range(cols):  # x
                in_img = open_image(next(paths))
                if in_img.format != 'RGB':
                    in_img = in_img.convert('RGB')
                yield in_img.resize(tile_size), (col * tile_width, y)


if __name__ == '__main__':
    main()
