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
from ds_tools.core import wrap_main
from ds_tools.images.compare import ComparableImage
from ds_tools.logging import init_logging

log = logging.getLogger(__name__)


def parser():
    # fmt: off
    parser = ArgParser(description='Compare images')
    parser.add_argument('path_a', help='Path to an image file')
    parser.add_argument('path_b', help='Path to an image file')
    parser.add_argument('--no_gray', '-G',  dest='gray', action='store_false', help='Do not normalize images to grayscale before comparisons')
    parser.add_argument('--no_normalize', '-N', dest='normalize', action='store_false', help='Do not normalize images for exposure differences before comparisons')
    parser.add_argument('--max_width', '-W', type=int, help='Resize images that have a width greater than this value')
    parser.add_argument('--max_height', '-H', type=int, help='Resize images that have a height greater than this value')
    parser.add_argument('--same', '-s', action='store_true', help='Include comparisons intended for images that are the same')
    parser.include_common_args('verbosity')
    # fmt: on
    return parser


@wrap_main
def main():
    args = parser().parse_args(req_subparser_value=True)
    init_logging(args.verbose, log_path=None)

    image_args = (args.gray, args.normalize, args.max_width, args.max_height)
    img_a = ComparableImage(Path(args.path_a).expanduser().resolve(), *image_args)
    img_b = ComparableImage(Path(args.path_b).expanduser().resolve(), *image_args)
    log.debug(f'Comparing {img_a} to {img_b}')

    methods = {
        'taxicab_distance': 'lower values = more similar',
        # 'zero_norm': '0-1',
        'mean_squared_error': 'lower values = more similar',
        'mean_structural_similarity': '0-1; higher values = more similar',
        'is_same_as': 'bool',
        'is_similar_to': 'bool',
    }
    if args.same:
        methods.update({
            'euclidean_root_mse': '',
            'min_max_root_mse': '',
            'mean_root_mse': '',
            'peak_signal_noise_ratio': 'higher values ~= higher quality if image A is an original version of image B',
        })

    for method, description in methods.items():
        result = getattr(img_a, method)(img_b)
        if isinstance(result, tuple):
            overall, per_pix = result
            log.info(f'{method:>26s}: {overall:17,.3f}  -  per pixel: {per_pix:10,.6f}  ({description})')
        else:
            if method in ('is_same_as', 'is_similar_to'):
                log.info(f'{method:>26s}: {result!r:>17}{" " * 26}  ({description})')
            else:
                log.info(f'{method:>26s}: {result:17,.3f}{" " * 26}  ({description})')

    # m_norm, z_norm, m_pix, z_pix = calc_distance(img_a, img_b)
    # log.info(f'Manhattan norm: {m_norm:14,.3f}  -  per pixel: {m_pix:,.6f}')
    # log.info(f'     Zero norm: {z_norm:14,.3f}  -  per pixel: {z_pix:,.6f}')


if __name__ == '__main__':
    main()
