#!/usr/bin/env python

from cli_command_parser import Command, ParamGroup, Positional, Option, Flag, Counter, main

from ds_tools.media.constants import NAME_RESOLUTION_MAP, ENCODER_CODEC_MAP


class Transcoder(Command, description='Transcode videos (requires ffmpeg)'):
    in_path = Positional(nargs='+', help='Input video file path')
    verbose = Counter('-v', help='Increase logging verbosity (can specify multiple times)')

    with ParamGroup(description='Input Options'):
        stream = Option('-s', type=int, help='Stream index for the video stream to use when calculating resolution/fps/etc')
        cuda = Flag(help='Use CUDA hardware acceleration for decoding the source')
        nvidia_decoder = Flag(help='Use an NVIDIA decoder for input, when possible')

    with ParamGroup(description='Output Options'):
        output = Option('-o', metavar='PATH', help='Output video file path')
        resolution = Option('-r', choices=NAME_RESOLUTION_MAP, help='Output resolution (default: same as input)')
        pixel_format = Option(help='Output pixel format (default: same as input) (see ffmpeg -pix_fmts)')
        fps = Option('-f', type=int, choices=(24, 25, 30, 50, 60), help='Output FPS (default: same as input)')

    with ParamGroup(description='Encoding Options'):
        encoding = Option('-e', default='av1', choices=sorted(set(ENCODER_CODEC_MAP.values())), help='Output encoding')
        passes = Option('-p', default=1, type=int, choices=(1, 2), help='Number of encoding passes to use')

    with ParamGroup(description='General Options'):
        ffmpeg = Option('-F', metavar='PATH', help='Path to the ffmpeg binary to use (default: ffmpeg)')

    def _init_command_(self):
        from ds_tools.logging import init_logging

        init_logging(self.verbose, log_path=None)

    def main(self):
        from ds_tools.media.encoders import Encoder
        from ds_tools.media.ffmpeg import load_config
        from ds_tools.media.videos import Video
        from ds_tools.media.ffmpeg import set_ffmpeg_path

        load_config()
        if self.ffmpeg:
            set_ffmpeg_path(self.ffmpeg)

        options = {
            'resolution': self.resolution,
            'fps': self.fps,
            'pixel_format': self.pixel_format,
            'in_codec': self.nvidia_decoder,
            'in_hw_accel': self.cuda,
        }

        for video in map(Video, self.in_path):
            v_stream = video.streams[self.stream] if self.stream else None
            encoder = Encoder.for_encoding(self.encoding, video, v_stream, options=options)
            encoder.encode(self.output, self.passes)


if __name__ == '__main__':
    main()
