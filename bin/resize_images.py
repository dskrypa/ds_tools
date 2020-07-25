#!/usr/bin/env python
"""
:author: Doug Skrypa
"""

import sys
from os import environ as env
from pathlib import Path

venv_path = Path(__file__).resolve().parents[1].joinpath('venv')
if not env.get('VIRTUAL_ENV') and venv_path.exists():
    import platform
    from subprocess import Popen
    ON_WINDOWS = platform.system().lower() == 'windows'
    bin_path = venv_path.joinpath('Scripts' if ON_WINDOWS else 'bin')
    env.update(PYTHONHOME='', VIRTUAL_ENV=venv_path.as_posix(), PATH='{}:{}'.format(bin_path.as_posix(), env['PATH']))
    sys.exit(Popen([bin_path.joinpath('python.exe' if ON_WINDOWS else 'python').as_posix()] + sys.argv, env=env).wait())

import logging
from functools import cached_property
from typing import Optional, Union, Tuple

from PIL import Image

sys.path.append(Path(__file__).resolve().parents[1].as_posix())
from ds_tools.__version__ import __author_email__, __version__
from ds_tools.argparsing import ArgParser
from ds_tools.core import wrap_main, iter_files, relative_path
from ds_tools.logging import init_logging

log = logging.getLogger(__name__)
Size = Union[float, Tuple[int, int]]

RESAMPLE_FILTERS = {
    'nearest': Image.NEAREST,
    'box': Image.BOX,
    'linear': Image.BILINEAR,
    'hamming': Image.HAMMING,
    'cubic': Image.BICUBIC,
    'lanczos': Image.LANCZOS,
}


def parser():
    filters = sorted(RESAMPLE_FILTERS.keys())
    all_filters = ['ALL'] + filters

    parser = ArgParser(description='Resize Images')

    simple_parser = parser.add_subparser('action', 'simple', 'Apply a simple resize operation to a batch of files')
    simple_parser.add_argument('path', nargs='+', help='The path(s) to the image file(s) that should be resized')
    simple_parser.add_argument('--output', '-o', metavar='PATH', help='Output directory to store modified files', required=True)
    opt_group = simple_parser.add_argument_group('Options')
    opt_group.add_argument('--rename', '-R', action='store_true', help='Rename files that have their resolution in the file name')
    opt_group.add_argument('--filter', '-f', choices=all_filters, default='nearest', help='Resample the image using the specified filter (default: %(default)s)')
    size_group = opt_group.add_argument_group('Size Options').add_mutually_exclusive_group()
    size_group.add_argument('--multiplier', '-m', type=float, help='Scale both dimensions by the given amount')
    size_group.add_argument('--size', '-s', metavar='WIDTH HEIGHT', type=int, nargs=2, help='The width and height to use')

    ud_parser = parser.add_subparser('action', 'updown', 'Enlarge and then shrink images using different filters')
    ud_parser.add_argument('path', nargs='+', help='The path(s) to the image file(s) that should be resized')
    ud_parser.add_argument('--output', '-o', metavar='PATH', help='Output directory to store modified files', required=True)
    ud_opt_group = ud_parser.add_argument_group('Options')
    ud_opt_group.add_argument('--rename', '-R', action='store_true', help='Rename files that have their resolution in the file name')
    ud_opt_group.add_argument('--filter_1', '-f1', choices=filters, default='nearest', help='Resample the image using the specified filter (default: %(default)s)')
    ud_opt_group.add_argument('--filter_2', '-f2', choices=filters, default='nearest', help='Resample the image using the specified filter (default: %(default)s)')
    size_group_1 = ud_opt_group.add_argument_group('Size 1 Options').add_mutually_exclusive_group()
    size_group_1.add_argument('--multiplier_1', '-m1', type=float, help='Scale both dimensions by the given amount')
    size_group_1.add_argument('--size_1', '-s1', metavar='WIDTH HEIGHT', type=int, nargs=2, help='The width and height to use')
    size_group_2 = ud_opt_group.add_argument_group('Size 2 Options').add_mutually_exclusive_group()
    size_group_2.add_argument('--multiplier_2', '-m2', type=float, help='Scale both dimensions by the given amount')
    size_group_2.add_argument('--size_2', '-s2', metavar='WIDTH HEIGHT', type=int, nargs=2, help='The width and height to use')

    parser.include_common_args('verbosity')
    return parser


@wrap_main
def main():
    args = parser().parse_args(req_subparser_value=True)
    init_logging(args.verbose, log_path=None)

    action = args.action
    if action == 'simple':
        resize_simple(args.path, args.output, args.size or args.multiplier, args.filter, args.rename)
    elif action == 'updown':
        resize_up_down(
            args.path,
            args.output,
            args.size_1 or args.multiplier_1,
            args.size_2 or args.multiplier_2,
            args.filter_1,
            args.filter_2,
            args.rename,
        )
    else:
        raise ValueError(f'Unexpected {action=!r}')


class ImageFile:
    def __init__(self, path: Path, image: Optional[Image.Image] = None, original: Optional['ImageFile'] =None):
        self.path = path
        self.image = image or Image.open(path)      # type: Image.Image
        self._original = original                   # type: Optional['ImageFile']

    @cached_property
    def rel_path(self) -> str:
        return relative_path(self.path)

    @cached_property
    def original(self) -> 'ImageFile':
        if self._original:
            return self._original.original
        return self

    def resize(self, size: Size, resample=None):
        old_w, old_h = self.image.size
        if isinstance(size, tuple):
            new_w, new_h = size
        else:
            new_w = int(round(old_w * size))
            new_h = int(round(old_h * size))

        if old_w == new_w and old_h == new_h:
            log.info(f'Skipping {self.rel_path} - it is already {old_w}x{old_h}')
            return self
        else:
            log.info(f'Resizing {self.rel_path} from {old_w}x{old_h} to {new_w}x{new_h}')
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


def resize_simple(paths, output_dir: str, size: Size, filter_name: str, rename=False):
    output_dir = validate_dir(Path(output_dir).expanduser().resolve())
    all_filters = filter_name == 'ALL'
    if all_filters:
        for name in RESAMPLE_FILTERS:
            validate_dir(output_dir.joinpath(name))

    resample_filter = None if all_filters else RESAMPLE_FILTERS[filter_name]

    for path in iter_files(paths):
        img = ImageFile(path)
        if all_filters:
            for name, resample_filter in RESAMPLE_FILTERS.items():
                img.resize(size, resample_filter).save(output_dir.joinpath(name), rename)
        else:
            img.resize(size, resample_filter).save(output_dir, rename)


def resize_up_down(paths, output_dir: str, size_1: Size, size_2: Size, filter_1: str, filter_2: str, rename=False):
    output_dir = validate_dir(Path(output_dir).expanduser().resolve())
    filter_1 = RESAMPLE_FILTERS[filter_1]
    filter_2 = RESAMPLE_FILTERS[filter_2]

    for path in iter_files(paths):
        img = ImageFile(path)
        img.resize(size_1, filter_1).resize(size_2, filter_2).save(output_dir, rename)


def validate_dir(path: Path):
    if path.is_file():
        raise ValueError(f'--output / -o must be a directory - {path} is a file')
    elif not path.exists():
        path.mkdir(parents=True)
    return path


if __name__ == '__main__':
    main()
