#!/usr/bin/env python

import sys
from pathlib import Path

sys.path.insert(0, Path(__file__).resolve().parents[1].joinpath('bin').as_posix())
import _venv  # This will activate the venv, if it exists and is not already active

import logging

from ds_tools.argparsing import ArgParser
from ds_tools.core.main import wrap_main
from ds_tools.media.constants import NAME_RESOLUTION_MAP, ENCODER_CODEC_MAP

log = logging.getLogger(__name__)


def parser():
    parser = ArgParser(description='Transcode videos (requires ffmpeg)')
    parser.add_argument('in_path', nargs='+', help='Input video file path')

    in_group = parser.add_argument_group('Input Options')
    in_group.add_argument('--stream', '-s', type=int, help='Stream index for the video stream to use when calculating resolution/fps/etc')
    in_group.add_argument('--cuda', action='store_true', help='Use CUDA hardware acceleration for decoding the source')
    in_group.add_argument('--nvidia_decoder', action='store_true', help='Use an NVIDIA decoder for input, when possible')

    out_group = parser.add_argument_group('Output Options')
    out_group.add_argument('--output', '-o', metavar='PATH', help='Output video file path')
    out_group.add_argument('--resolution', '-r', choices=NAME_RESOLUTION_MAP.keys(), help='Output resolution (default: same as input)')
    out_group.add_argument('--pixel_format', help='Output pixel format (default: same as input) (see ffmpeg -pix_fmts)')
    out_group.add_argument('--fps', '-f', type=int, choices=(24, 25, 30, 50, 60), help='Output FPS (default: same as input)')

    encodings = sorted(set(ENCODER_CODEC_MAP.values()))
    enc_group = parser.add_argument_group('Encoding Options')
    enc_group.add_argument('--encoding', '-e', choices=encodings, default='av1', help='Output encoding')
    enc_group.add_argument('--passes', '-p', type=int, default=1, choices=(1, 2), help='Number of encoding passes to use')

    gen_group = parser.add_argument_group('General Options')
    gen_group.add_argument('--ffmpeg', '-F', metavar='PATH', help='Path to the ffmpeg binary to use (default: ffmpeg)')

    parser.include_common_args('verbosity')
    return parser


@wrap_main
def main():
    args = parser().parse_args()

    from ds_tools.logging import init_logging
    init_logging(args.verbose, log_path=None)

    from ds_tools.media.encoders import Encoder
    from ds_tools.media.ffmpeg import load_config
    from ds_tools.media.videos import Video
    from ds_tools.media.ffmpeg import set_ffmpeg_path

    load_config()
    if args.ffmpeg:
        set_ffmpeg_path(args.ffmpeg)

    options = {
        'resolution': args.resolution,
        'fps': args.fps,
        'pixel_format': args.pixel_format,
        'in_codec': args.nvidia_decoder,
        'in_hw_accel': args.cuda,
    }

    for video in map(Video, args.in_path):
        v_stream = video.streams[args.stream] if args.stream else None
        encoder = Encoder.for_encoding(args.encoding, video, v_stream, options=options)
        encoder.encode(args.output, args.passes)


if __name__ == '__main__':
    main()
