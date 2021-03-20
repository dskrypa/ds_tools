#!/usr/bin/env python

import sys
from pathlib import Path

sys.path.insert(0, Path(__file__).resolve().parents[1].joinpath('bin').as_posix())
import _venv  # This will activate the venv, if it exists and is not already active

import logging

from ds_tools.argparsing import ArgParser
from ds_tools.http.utils import enable_http_debug_logging
from ds_tools.logging import init_logging
from ds_tools.m3u8.stream import VideoStream, GoplayVideoStream

log = logging.getLogger(__name__)


def parser():
    parser = ArgParser(description='Download and merge split videos in a M3U8 playlist')

    parser.add_argument('source', help='URL that provides stream info or path to a .m3u8 file')
    parser.add_argument('--name', '-n', help='The name of the video being downloaded (without extension)', required=True)
    parser.add_argument('--save_dir', '-d', default='~/Downloads/m3u8/', help='Directory to store downloads')
    parser.add_argument('--local', '-l', action='store_true', help='Specify if the target ts part files already exist')
    parser.add_argument('--format', '-f', default='mp4', choices=('mp4', 'mkv'), help='Video format (default: %(default)s)')
    parser.add_argument('--goplay', '-g', action='store_true', help='The info url is a goplay.anontpp.com dl code')
    parser.add_argument('--ffmpeg_dl', '-F', action='store_true', help='Have ffmpeg process the m3u8 and download the video parts instead (slower & more error prone)')

    parser.add_common_arg('--debug', '-D', action='store_true', help='Enable HTTP debugging')
    parser.include_common_args('verbosity', parallel=4)
    return parser


def main():
    args = parser().parse_args()
    init_logging(args.verbose, log_path=None)

    if args.debug:
        enable_http_debug_logging()

    cls = GoplayVideoStream if args.goplay else VideoStream
    video = cls(args.source, args.save_dir, args.name, args.format, args.local, args.ffmpeg_dl)
    if args.local or args.ffmpeg_dl:
        video.save_via_ffmpeg()
    else:
        video.download(args.parallel)


if __name__ == '__main__':
    main()
