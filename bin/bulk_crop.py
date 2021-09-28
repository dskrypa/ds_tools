#!/usr/bin/env python

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, PROJECT_ROOT.joinpath('bin').as_posix())
import _venv  # This will activate the venv, if it exists and is not already active

import logging

sys.path.append(PROJECT_ROOT.as_posix())
from ds_tools.__version__ import __author_email__, __version__
from ds_tools.argparsing import ArgParser
from ds_tools.core.main import wrap_main
from ds_tools.fs.paths import unique_path
from ds_tools.images.utils import as_image
from ds_tools.logging import init_logging

log = logging.getLogger(__name__)


def parser():
    # fmt: off
    parser = ArgParser(description='Compare images')
    parser.add_argument('paths', nargs='+', help='Path to an image file')
    parser.add_argument('--position', '-p', nargs=2, type=int, default=(0, 0), help='Top left corner x, y coordinates')
    parser.add_argument('--size', '-s', nargs=2, type=int, help='Size (width, height) of the area to crop to', required=True)
    parser.include_common_args('verbosity')
    # fmt: on
    return parser


@wrap_main
def main():
    args = parser().parse_args(req_subparser_value=True)
    init_logging(args.verbose, log_path=None)

    x, y = args.position
    width, height = args.size
    box = (x, y, x + width, y + height)

    for path in args.paths:
        src_path = Path(path).expanduser().resolve()
        dst_path = unique_path(
            src_path.parent, f'{src_path.stem}_{x}x{y}+{width}x{height}', src_path.suffix, add_date=False
        )
        log.info(f'Saving {dst_path.name}')
        as_image(src_path).crop(box).save(dst_path)


if __name__ == '__main__':
    main()
