#!/usr/bin/env python

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, PROJECT_ROOT.joinpath('bin').as_posix())
import _venv  # This will activate the venv, if it exists and is not already active

import logging
from functools import cached_property
from typing import Optional, Union, Tuple

from cli_command_parser import Command, Option, Counter, Positional, SubCommand, ParamGroup, Flag, inputs, main
from PIL.Image import Image as PILImage, Resampling, open as image_open  # noqa

sys.path.append(PROJECT_ROOT.as_posix())
from ds_tools.__version__ import __author_email__, __version__
from ds_tools.fs.paths import iter_files, relative_path
from ds_tools.logging import init_logging

log = logging.getLogger(__name__)
Size = Union[float, Tuple[int, int]]

RESAMPLE_FILTERS = {
    'box': Resampling.BOX,
    'cubic': Resampling.BICUBIC,
    'hamming': Resampling.HAMMING,
    'lanczos': Resampling.LANCZOS,
    'linear': Resampling.BILINEAR,
    'nearest': Resampling.NEAREST,
}


class Resizer(Command, description='Resize Images'):
    sub_cmd = SubCommand()
    verbose = Counter('-v', help='Increase logging verbosity (can specify multiple times)')
    output: Path = Option(
        '-o', type=inputs.Path(type='dir', resolve=True), required=True, help='Output directory to store modified files'
    )
    # dry_run = Flag('-D', help='Print the actions that would be taken instead of taking them')

    def _init_command_(self):
        init_logging(self.verbose, log_path=None)
        if not self.output.exists():
            self.output.mkdir(parents=True)


class Simple(Resizer):
    paths = Positional(nargs='+', help='The path(s) to the image file(s) that should be resized')

    with ParamGroup('Options'):
        rename = Flag('-R', help='Rename files that have their resolution in the file name')
        filter = Option('-f', choices=['ALL', *RESAMPLE_FILTERS], default='lanczos', help='Resample the image using the specified filter')
    with ParamGroup('Size Options', mutually_exclusive=True):
        multiplier: float = Option('-m', help='Scale both dimensions by the given amount')
        size: tuple[int, int] = Option('-s', nargs=2, metavar='WIDTH HEIGHT', help='The width and height to use')

    def main(self):
        if self.filter == 'ALL':
            out_dirs = {(name, f): self.output.joinpath(name) for name, f in RESAMPLE_FILTERS.items()}
            for out_dir in out_dirs:
                if not out_dir.exists():
                    out_dir.mkdir(parents=True)
        else:
            out_dirs = {(self.filter, RESAMPLE_FILTERS[self.filter]): self.output}

        size = self.size or self.multiplier
        log.info(f'Using {size=}')
        for path in iter_files(self.paths):
            img = ImageFile(path)
            for (name, resample_filter), out_dir in out_dirs.items():
                img.resize(size, resample_filter).save(out_dir, self.rename)


class Updown(Resizer):
    paths = Positional(nargs='+', help='The path(s) to the image file(s) that should be resized')
    with ParamGroup('Options'):
        rename = Flag('-R', help='Rename files that have their resolution in the file name')
        filter_1 = Option('-f1', choices=RESAMPLE_FILTERS, default='lanczos', help='Resample the image using the specified filter')
        filter_2 = Option('-f2', choices=RESAMPLE_FILTERS, default='lanczos', help='Resample the image using the specified filter')
    with ParamGroup('Size 1 Options', mutually_exclusive=True):
        multiplier_1: float = Option('-m1', help='Scale both dimensions by the given amount')
        size_1: tuple[int] = Option('-s1', nargs=2, metavar='WIDTH HEIGHT', help='The width and height to use')
    with ParamGroup('Size 2 Options', mutually_exclusive=True):
        multiplier_2: float = Option('-m2', help='Scale both dimensions by the given amount')
        size_2: tuple[int] = Option('-s2', nargs=2, metavar='WIDTH HEIGHT', help='The width and height to use')

    def main(self):
        filter_1 = RESAMPLE_FILTERS[self.filter_1]
        filter_2 = RESAMPLE_FILTERS[self.filter_2]

        size_1 = self.size_1 or self.multiplier_1
        size_2 = self.size_2 or self.multiplier_2

        for path in iter_files(self.paths):
            img = ImageFile(path)
            img.resize(size_1, filter_1).resize(size_2, filter_2).save(self.output, self.rename)


class ImageFile:
    def __init__(self, path: Path, image: Optional[PILImage] = None, original: Optional[ImageFile] = None):
        self.path = path
        self.image = image or image_open(path)      # type: PILImage
        self._original = original                   # type: Optional['ImageFile']

    def __repr__(self) -> str:
        w, h = self.image.size
        return f'<ImageFile({self.rel_path!r})[{w}x{h}]>'

    @cached_property
    def rel_path(self) -> str:
        return relative_path(self.path)

    @cached_property
    def original(self) -> ImageFile:
        if self._original:
            return self._original.original
        return self

    def resize(self, size: Size, resample=None):
        old_w, old_h = self.image.size
        log.debug(f'Resizing from {(old_w, old_h)} to {size=}')
        try:
            new_w, new_h = size
        except (TypeError, ValueError):
            new_w = int(round(old_w * size))
            new_h = int(round(old_h * size))

        if old_w == new_w and old_h == new_h:
            log.info(f'Skipping {self.rel_path} - it is already {old_w}x{old_h}')
            return self
        else:
            log.info(f'Resizing {self.rel_path} from {old_w}x{old_h} to {new_w}x{new_h} with {resample=}')
            resized = self.image.resize((new_w, new_h), resample)
            return self.__class__(self.path, resized, self)

    def save(self, out_dir: Path, rename=False):
        dest_name = self.path.name
        if rename and self.original:
            old_w, old_h = self.original.image.size
            new_w, new_h = self.image.size
            dest_name = dest_name.replace(f'{old_w}x{old_h}', f'{new_w}x{new_h}')

        dest_path = out_dir.joinpath(dest_name)
        log.info(f'Saving {self.rel_path} as {relative_path(dest_path)}')
        self.image.save(dest_path)
        self.path = dest_path


if __name__ == '__main__':
    main()
