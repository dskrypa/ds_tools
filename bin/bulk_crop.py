#!/usr/bin/env python

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, PROJECT_ROOT.joinpath('bin').as_posix())
import _venv  # This will activate the venv, if it exists and is not already active

from concurrent.futures import as_completed, ProcessPoolExecutor
from datetime import datetime
from typing import Optional

sys.path.append(PROJECT_ROOT.as_posix())
from ds_tools.__version__ import __author_email__, __version__
from ds_tools.argparsing import ArgParser
from ds_tools.core.main import wrap_main
from ds_tools.fs.paths import unique_path
from ds_tools.images.utils import as_image, Box
from ds_tools.logging import init_logging


def parser():
    # fmt: off
    parser = ArgParser(description='Crop multiple images with the same dimensions')
    parser.add_argument('paths', nargs='+', help='Path to an image file')
    parser.add_argument('--position', '-p', nargs=2, type=int, default=(0, 0), help='Top left corner x, y coordinates')
    parser.add_argument('--size', '-s', nargs=2, type=int, help='Size (width, height) of the area to crop to', required=True)
    parser.add_argument('--output', '-o', metavar='PATH', help='Output directory (default: same directory as original)')
    parser.add_argument('--date_prefix', '-d', help='Rename output files with the given prefix and the modification date (useful for [win]+[print screen] screenshots)')
    parser.add_argument('--no_suffix', '-n', action='store_true', help='Do not include a pos/size suffix (only allowed when --output/-o is specified)')
    parser.include_common_args('verbosity', parallel=1)
    # fmt: on
    return parser


@wrap_main
def main():
    args = parser().parse_args()
    init_logging(args.verbose, log_path=None)

    if args.output:
        dst_dir = Path(args.output).expanduser().resolve()
        if not dst_dir.exists():
            dst_dir.mkdir(parents=True)
        elif not dst_dir.is_dir():
            raise ValueError(f'Invalid --output / -o value - {dst_dir.as_posix()!r} is not a directory')
    else:
        dst_dir = None

    if args.no_suffix and not dst_dir:
        raise ValueError('--no_suffix / -n may only be used if --output / -o is also specified')

    x, y = args.position
    width, height = args.size
    box = (x, y, x + width, y + height)
    suffix = '' if args.no_suffix else f'{x}x{y}+{width}x{height}'

    if args.parallel > 1:
        with ProcessPoolExecutor(max_workers=args.parallel) as executor:
            futures = {
                executor.submit(crop_image, path, dst_dir, suffix, box, args.date_prefix): path
                for path in map(lambda p: Path(p).expanduser().resolve(), args.paths)
            }
            try:
                for future in as_completed(futures):
                    result = future.result()
            except BaseException:
                executor.shutdown(wait=True, cancel_futures=True)
                raise
    else:
        for path in args.paths:
            src_path = Path(path).expanduser().resolve()
            crop_image(src_path, dst_dir, suffix, box, args.date_prefix)


def crop_image(src_path: Path, dst_dir: Optional[Path], suffix: str, box: Box, prefix: Optional[str] = None):
    if prefix:
        name_parts = [prefix, datetime.fromtimestamp(src_path.stat().st_mtime).strftime('%Y-%m-%d_%H.%M.%S')]
    else:
        name_parts = [src_path.stem]

    if suffix:
        name_parts.append(suffix)

    dst_path = unique_path(dst_dir or src_path.parent, '_'.join(name_parts), src_path.suffix, add_date=False)
    print(f'Saving {dst_path.name}')
    try:
        as_image(src_path).crop(box).save(dst_path)
    except BaseException:
        if dst_path.exists():  # It will be incomplete
            dst_path.unlink()
        raise


if __name__ == '__main__':
    main()
