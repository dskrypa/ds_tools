#!/usr/bin/env python

from concurrent.futures import as_completed, ProcessPoolExecutor
from datetime import datetime
from pathlib import Path

from cli_command_parser import Command, ParamGroup, Positional, Option, Flag, Counter, main
from cli_command_parser.inputs import Path as IPath

from ds_tools.__version__ import __author_email__, __version__  # noqa
from ds_tools.fs.paths import unique_path
from ds_tools.images.utils import as_image, Box


class BulkCropper(Command, description='Crop multiple images with the same dimensions'):
    paths = Positional(nargs='+', type=IPath(type='file', exists=True), help='Path to an image file')

    with ParamGroup('Crop'):
        position = Option('-p', default=(0, 0), type=int, nargs=2, help='Top left corner x, y coordinates')
        size = Option('-s', required=True, type=int, nargs=2, help='Size (width, height) of the area to crop to')

    with ParamGroup('Output'):
        output = Option('-o', type=IPath(type='dir'), help='Output directory (default: same directory as original)')
        date_prefix = Option('-d', help='Rename output files with the given prefix and the modification date (useful for [win]+[print screen] screenshots)')
        no_suffix = Flag('-n', help='Do not include a pos/size suffix (only allowed when --output/-o is specified)')

    with ParamGroup('Common'):
        verbose = Counter('-v', help='Increase logging verbosity (can specify multiple times)')
        parallel = Option('-P', default=1, type=int, help='Maximum number of workers to use in parallel')

    def _init_command_(self):
        from ds_tools.logging import init_logging

        init_logging(self.verbose, log_path=None)

    def main(self):
        if (dst_dir := self.output) and not dst_dir.exists():
            dst_dir.mkdir(parents=True)

        if self.no_suffix and not dst_dir:
            raise ValueError('--no_suffix / -n may only be used if --output / -o is also specified')

        x, y = self.position
        width, height = self.size
        box = (x, y, x + width, y + height)
        suffix = '' if self.no_suffix else f'{x}x{y}+{width}x{height}'

        if self.parallel > 1:
            with ProcessPoolExecutor(max_workers=self.parallel) as executor:
                futures = {executor.submit(self.crop_image, path, suffix, box): path for path in self.paths}
                try:
                    for future in as_completed(futures):
                        _ = future.result()
                except BaseException:
                    executor.shutdown(wait=True, cancel_futures=True)
                    raise
        else:
            for src_path in self.paths:
                self.crop_image(src_path, suffix, box)

    def crop_image(self, src_path: Path, suffix: str, box: Box):
        if prefix := self.date_prefix:
            name_parts = [prefix, datetime.fromtimestamp(src_path.stat().st_mtime).strftime('%Y-%m-%d_%H.%M.%S')]
        else:
            name_parts = [src_path.stem]

        if suffix:
            name_parts.append(suffix)

        dst_path = unique_path(self.output or src_path.parent, '_'.join(name_parts), src_path.suffix, add_date=False)
        print(f'Saving {dst_path.name}')
        try:
            as_image(src_path).crop(box).save(dst_path)
        except BaseException:
            dst_path.unlink(missing_ok=True)  # It would be incomplete
            raise


if __name__ == '__main__':
    main()
