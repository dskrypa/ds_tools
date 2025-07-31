#!/usr/bin/env python

from __future__ import annotations

import logging
from concurrent.futures import as_completed, ProcessPoolExecutor
from datetime import datetime
from multiprocessing import set_start_method
from pathlib import Path
from typing import TYPE_CHECKING

from cli_command_parser import Command, ParamGroup, Positional, Option, Flag, TriFlag, Counter, main
from cli_command_parser.inputs import Path as IPath
from tqdm import tqdm

from ds_tools.fs.paths import unique_path, iter_files
from ds_tools.images.array import ImageArray
from ds_tools.images.utils import as_image

if TYPE_CHECKING:
    from PIL.Image import Image as PILImage
    from ds_tools.images.typing import IntBox

log = logging.getLogger(__name__)
EXISTING_PATH = IPath(type='file|dir', exists=True)


class BulkCropper(Command, show_group_tree=True):
    """Crop multiple images with the same dimensions"""

    paths = Positional(nargs='+', type=EXISTING_PATH, help='Path to an image file or a directory containing images')

    with ParamGroup('Crop', mutually_exclusive=True, required=True):
        auto = Flag('-a', help='Automatically crop to the visible image')
        auto_find = Flag('-A', help='Automatically crop to the visible image using custom bbox detection')
        with ParamGroup():
            size = Option('-s', required=True, type=int, nargs=2, help='Size (width, height) of the area to crop to')
            position = Option('-p', type=int, nargs=2, help='Top left corner x, y coordinates')

    with ParamGroup('Output'):
        output = Option('-o', type=IPath(type='dir'), help='Output directory (default: same directory as original)')
        date_prefix = Option('-d', help='Rename output files with the given prefix and the modification date (useful for [win]+[print screen] screenshots)')
        split_by_date = Flag(help='Sort output files into dated directories')
        suffix = TriFlag(help='Whether a pos/size suffix should be included (default: True if --output/-o is not specified, False otherwise)')

        @suffix.register_default_cb
        def _suffix(self) -> bool:
            return not self.output

    with ParamGroup('Common'):
        verbose = Counter('-v', help='Increase logging verbosity (can specify multiple times)')
        parallel = Option('-P', default=4, type=int, help='Maximum number of workers to use in parallel')

    def _init_command_(self):
        from ds_tools.logging import init_logging

        init_logging(self.verbose, log_path=None)
        set_start_method('spawn')

    def main(self):
        if self.output:
            self.output.mkdir(parents=True, exist_ok=True)
        elif not self.suffix:
            raise ValueError('--no-suffix may only be used if --output / -o is also specified')

        # TODO: Move to trash after crop option

        if self.parallel > 1:
            self._crop_all_mp()
        else:
            self._crop_all_st()

    def crop_image(self, src_path: Path):
        image = as_image(src_path)
        box = self._get_box(image)
        log.debug(f'Cropping image with bbox={box}')
        dst_path, rel_path = self._get_dst_path(src_path, box)
        log.debug(f'Saving {rel_path}')
        try:
            image.crop(box).save(dst_path)
        except BaseException:
            dst_path.unlink(missing_ok=True)  # It would be incomplete
            raise

    def _crop_all_mp(self):
        files = self._get_files()
        with ProcessPoolExecutor(max_workers=self.parallel) as executor:
            futures = {executor.submit(self.crop_image, path): path for path in files}
            try:
                with tqdm(total=len(files), unit='img', smoothing=0.1, maxinterval=1) as prog_bar:
                    for future in as_completed(futures):
                        _ = future.result()
                        prog_bar.update()
            except BaseException:
                executor.shutdown(wait=True, cancel_futures=True)
                raise

    def _crop_all_st(self):
        files = self._get_files()
        with tqdm(total=len(files), unit='img', smoothing=0.1, maxinterval=1) as prog_bar:
            for src_path in files:
                self.crop_image(src_path)
                prog_bar.update()

    def _get_files(self) -> list[Path]:
        # TODO: Skip thumbnails
        if files := list(iter_files(self.paths)):
            return files
        raise ValueError('No image files were found in the specified location(s)')

    def _get_box(self, image: PILImage) -> IntBox:
        if self.auto_find:
            # Note: Even when using alpha_only=False with `PIL.Image.Image.getbbox`, some letterboxing does not get
            # detected
            return ImageArray(image).find_bbox().as_bbox()
        elif self.auto:
            return image.getbbox()

        x, y = self.position or (0, 0)
        width, height = self.size
        return x, y, x + width, y + height

    def _get_dst_path(self, src_path: Path, box: IntBox) -> tuple[Path, str]:
        if prefix := self.date_prefix:
            name_parts = [prefix, datetime.fromtimestamp(src_path.stat().st_mtime).strftime('%Y-%m-%d_%H.%M.%S')]
        else:
            name_parts = [src_path.stem]

        if self.suffix:
            name_parts.append(box_suffix(box))

        dst_base = dst_dir = self.output or src_path.parent
        if self.split_by_date:
            dst_dir /= datetime.fromtimestamp(src_path.stat().st_mtime).strftime('%Y-%m-%d')
            dst_dir.mkdir(parents=True, exist_ok=True)

        dst_path = unique_path(dst_dir, '_'.join(name_parts), src_path.suffix)
        return dst_path, dst_path.relative_to(dst_base).as_posix()


def box_suffix(box: IntBox) -> str:
    x, y, xw, yh = box
    width = xw - x
    height = yh - y
    return f'{x}x{y}+{width}x{height}'


if __name__ == '__main__':
    main()
