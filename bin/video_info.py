#!/usr/bin/env python

from cli_command_parser import Command, Positional, Option, Flag, Counter, main

from ds_tools.output.constants import PRINTER_FORMATS


class VideoInfo(Command, description='View video metadata (requires ffmpeg)'):
    path = Positional(help='Path to a video file')
    format = Option('-f', choices=PRINTER_FORMATS, help='Output format for raw output (default: pre-selected fields)')
    keyframe_interval = Flag('-ki', help='Calculate and display keyframe interval for video streams')
    verbose = Counter('-v', help='Increase logging verbosity (can specify multiple times)')

    def _init_command_(self):
        from ds_tools.logging import init_logging

        init_logging(self.verbose, log_path=None)

    def main(self):
        from ds_tools.media.ffmpeg import load_config
        from ds_tools.media.videos import Video

        options = {'keyframe_interval': self.keyframe_interval}
        load_config()
        Video(self.path).print_info(self.format, options=options)

        # https://github.com/PyAV-Org/PyAV
        # import av
        # import av.datasets
        # # from av.container import Container, OutputContainer, InputContainer
        #
        # with av.open(args.path, 'r') as container:
        #     container


if __name__ == '__main__':
    main()
