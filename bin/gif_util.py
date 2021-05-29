#!/usr/bin/env python

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, PROJECT_ROOT.joinpath('bin').as_posix())
import _venv  # This will activate the venv, if it exists and is not already active

import json
import logging

sys.path.append(PROJECT_ROOT.as_posix())
from ds_tools.__version__ import __author_email__, __version__
from ds_tools.argparsing import ArgParser
from ds_tools.core.main import wrap_main
from ds_tools.core.serialization import PermissiveJSONEncoder
from ds_tools.logging import init_logging
from ds_tools.images.gif import AnimatedGif

log = logging.getLogger(__name__)


def parser():
    parser = ArgParser(description='Utility for working with animated GIFs')

    alpha_parser = parser.add_subparser('action', 'c2a', help='Convert the specified color to alpha')
    alpha_parser.add_argument('path', help='Path to the input file')
    alpha_parser.add_argument('output', help='Path for the output file')
    alpha_parser.add_argument('--color', '-c', metavar='RGB', help='Color to convert to alpha as an RGB hex code', required=True)
    alpha_parser.add_argument('--disposal', '-d', type=int, nargs='+', help='Way to treat the graphic after displaying it. Specify 1 value to apply to all, or per-frame values. 1: Do not dispose; 2: Restore to bg color; 3: Restore to prev content')
    # alpha_parser.add_argument('--threshold', '-t', type=float, default=0.95, help='Threshold to convert to alpha')

    split_parser = parser.add_subparser('action', 'split', help='Save each frame of an animated gif as a separate file')
    split_parser.add_argument('path', help='Path to the input file')
    split_parser.add_argument('output_dir', help='Path to the input file')
    split_parser.add_argument('--prefix', '-p', default='frame_', help='Frame filename prefix')
    split_parser.add_argument('--format', '-f', default='PNG', help='Image format for output files')

    combine_parser = parser.add_subparser('action', 'combine', help='Combine multiple images into a single animated gif')
    combine_parser.add_argument('paths', nargs='+', help='Input file paths')
    combine_parser.add_argument('--output', '-o', metavar='PATH', help='Output file path', required=True)
    combine_parser.add_argument('--disposal', type=int, nargs='+', help='Way to treat the graphic after displaying it. Specify 1 value to apply to all, or per-frame values. 1: Do not dispose; 2: Restore to bg color; 3: Restore to prev content')
    combine_parser.add_argument('--duration', '-d', type=int, nargs='+', help='Duration between frames in milliseconds. Specify 1 value to apply to all, or per-frame values')

    info_parser = parser.add_subparser('action', 'info', help='Display information about the given image')
    info_parser.add_argument('path', help='Path to the input file')
    info_parser.add_argument('--frames', '-f', action='store_true', help='Show information about each frame')

    parser.include_common_args('verbosity')
    return parser


@wrap_main
def main():
    args = parser().parse_args()
    init_logging(args.verbose, log_path=None, names=None)

    action = args.action
    if action == 'c2a':
        orig = AnimatedGif(args.path)
        updated = orig.color_to_alpha(args.color)
        disposal = _int_or_list(args.disposal)
        updated.save(args.output, duration=orig.info['duration'], transparency=0, disposal=disposal)
    elif action == 'split':
        AnimatedGif(args.path).save_frames(args.output_dir, prefix=args.prefix, format=args.format)
    elif action == 'combine':
        kwargs = dict(zip(('disposal', 'duration'), map(_int_or_list, (args.disposal, args.duration))))
        AnimatedGif(args.paths).save(args.output, **kwargs)
    elif action == 'info':
        show_info(Path(args.path).resolve(), args.frames)
    else:
        raise ValueError(f'Unsupported {action=}')


def _int_or_list(value):
    if not value:
        return None
    return value[0] if len(value) == 1 else value


def show_info(path: Path, show_frames: bool):
    image = AnimatedGif(path)
    if show_frames:
        for i, info in enumerate(image.get_info(True)):
            print_info(f'Frame {i}', info)
    else:
        print_info(path.as_posix(), image.get_info())


def print_info(identifier, info):
    print(f'---\n{identifier}:')
    for key, val in sorted(info.items()):
        if not isinstance(val, (str, int, float)):
            val = json.dumps(val, cls=PermissiveJSONEncoder)
        print(f'  {key}: {val}')


if __name__ == '__main__':
    main()
