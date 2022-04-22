#!/usr/bin/env python

import sys
from pathlib import Path

sys.path.insert(0, Path(__file__).resolve().parents[1].joinpath('bin').as_posix())
import _venv  # This will activate the venv, if it exists and is not already active

import logging

from ds_tools.argparsing import ArgParser
from ds_tools.core.main import wrap_main
from ds_tools.output.constants import PRINTER_FORMATS

log = logging.getLogger(__name__)


def parser():
    parser = ArgParser(description='View video metadata (requires ffmpeg)')
    parser.add_argument('path', help='Path to a video file')
    parser.add_argument('--format', '-f', choices=PRINTER_FORMATS, help='Output format for raw output (default: pre-selected fields)')
    parser.add_argument('--keyframe_interval', '-ki', action='store_true', help='Calculate and display keyframe interval for video streams')
    parser.include_common_args('verbosity')
    return parser


@wrap_main
def main():
    args = parser().parse_args()

    from ds_tools.logging import init_logging
    init_logging(args.verbose, log_path=None)

    from ds_tools.media.ffmpeg import load_config
    from ds_tools.media.videos import Video

    options = {'keyframe_interval': args.keyframe_interval}

    load_config()
    Video(args.path).print_info(args.format, options=options)


if __name__ == '__main__':
    main()
