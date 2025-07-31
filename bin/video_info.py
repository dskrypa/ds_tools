#!/usr/bin/env python

from __future__ import annotations

from functools import cached_property
from typing import TYPE_CHECKING

from cli_command_parser import Command, Positional, Option, Flag, Counter, ParamGroup, main

from ds_tools.output.constants import PRINTER_FORMATS

if TYPE_CHECKING:
    from ds_tools.media.videos import Video

STREAM_TYPES = ('video', 'audio', 'subtitle')


class VideoInfo(Command, description='View video metadata (requires ffmpeg)'):
    path = Positional(nargs='+', help='Path to one or more video files')
    recursive = Flag('-r', help='Process directories recursively')

    with ParamGroup('Output'):
        format = Option(
            '-f', choices=PRINTER_FORMATS, help='Output format for raw output (default: pre-selected fields)'
        )
        full = Flag(help='Print full info (default: filtered)')

    keyframe_interval = Flag('-ki', help='Calculate and display keyframe interval for video streams')
    stream_types = Option(
        '-t', nargs='+', choices=STREAM_TYPES, help='Only include the specified stream types (default: all)'
    )
    verbose = Counter('-v', help='Increase logging verbosity (can specify multiple times)')

    def _init_command_(self):
        from ds_tools.logging import init_logging

        init_logging(self.verbose, log_path=None)

    def main(self):
        from ds_tools.fs.paths import iter_files
        from ds_tools.media.ffmpeg import load_config
        from ds_tools.media.videos import Video

        load_config()
        for file_path in iter_files(self.path, self.recursive):
            self._print_info(Video(file_path))

        # https://github.com/PyAV-Org/PyAV
        # import av
        # import av.datasets
        # # from av.container import Container, OutputContainer, InputContainer
        #
        # with av.open(args.path, 'r') as container:
        #     container

    def _print_info(self, video: Video):
        if self.format:
            self._print_structured(video)
        else:
            self._print_other(video)

    def _print_structured(self, video: Video):
        from ds_tools.output.printer import Printer

        Printer(self.format).pprint(video.info if self.full else video.filtered_info())

    def _print_other(self, video: Video):
        options = {'keyframe_interval': self.keyframe_interval}
        types = self.stream_types or STREAM_TYPES

        sections = {'File': video.get_info()}
        sections |= {
            f'Stream #{i} ({s.type})': s.get_info(options) for i, s in enumerate(video.streams) if s.type in types
        }

        keys = {k for header, info in sections.items() for k in info}
        max_width = max(map(len, keys)) + 1
        format_row = f'{{:{max_width}s}}  {{}}'.format

        for i, (header, info) in enumerate(sections.items()):
            self._print_header(header, color=None if i else 11)
            for key, val in info.items():
                print(format_row(key + ':', val))

    def _print_header(self, text: str, char: str = '-', color: str | int | None = None):
        from ds_tools.output.color import colored

        width = (self._terminal_width - len(text) - 4) // 2
        width = max(width, 4)
        if len(text) % 2 != self._terminal_width % 2:
            left = char * width
            right = char * (width + 1)
        else:
            left = right = char * width

        print(colored(f'{left}  {text}  {right}', color))

    @cached_property
    def _terminal_width(self) -> int:
        from shutil import get_terminal_size

        return get_terminal_size().columns - 1


if __name__ == '__main__':
    main()
