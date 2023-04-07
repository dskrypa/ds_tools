#!/usr/bin/env python

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from cli_command_parser import Command, SubCommand, Positional, Option, Counter, main, inputs

from ds_tools.caching.decorators import cached_property

if TYPE_CHECKING:
    from pytube import YouTube

log = logging.getLogger(__name__)
DEFAULT_DIR = Path('~/Downloads/youtube/').expanduser()


class YouTubeCLI(Command, description='Download YouTube videos'):
    action = SubCommand()
    verbose = Counter('-v', help='Increase logging verbosity (can specify multiple times)')
    url: str

    def _init_command_(self):
        from ds_tools.logging import init_logging

        init_logging(self.verbose, log_path=None)

    @cached_property
    def yt(self) -> YouTube:
        from pytube import YouTube

        return YouTube(self.url)


class Dl(YouTubeCLI, help='Download a video from YouTube'):
    url = Positional(metavar='URL', help='The name URL of the video to download')
    save_dir = Option('-d', type=inputs.Path(type='dir'), default=DEFAULT_DIR, help='Directory to store downloads')
    resolution = Option('-r', default='1080p', help='Video resolution')
    extension = Option('-e', default='mp4', help='Video extension')

    def main(self):
        from tempfile import TemporaryDirectory
        from ds_tools.input import choose_item

        if not self.save_dir.exists():
            self.save_dir.mkdir(parents=True)

        with TemporaryDirectory() as tmp_dir:
            choices = self.yt.streams.order_by('resolution')
            vid_stream = choose_item(choices.fmt_streams, 'stream')
            # vid_stream = self.yt.streams.filter(file_extension=self.extension, res=self.resolution).order_by('resolution')[-1]

            log.info(f'Downloading video={vid_stream}')
            vid_path = Path(vid_stream.download(output_path=tmp_dir))

            choices = self.yt.streams.filter(type='audio').order_by('abr')
            audio_stream = choose_item(choices, 'audio stream')

            # audio_stream = self.yt.streams.filter(type='audio').order_by('abr')[-1]
            log.info(f'Downloading audio={audio_stream}')
            audio_path = Path(audio_stream.download(output_path=tmp_dir))

            dest_path = self.save_dir.joinpath(vid_stream.default_filename)
            combine_via_ffmpeg(audio_path, vid_path, dest_path)
            log.info(f'Saved video to {dest_path}')


class List(YouTubeCLI, help='List available parts for the given YouTube video'):
    url = Positional(help='The name URL of the video to download')

    def main(self):
        print('Video:')
        for stream in self.yt.streams.filter(type='video').order_by('resolution'):
            print(f'    {stream}')

        print('\nAudio:')
        for stream in self.yt.streams.filter(type='audio').order_by('abr'):
            print(f'    {stream}')


class Audio(YouTubeCLI, help='Download audio from YouTube'):
    url = Positional(help='The name URL of the video to download')
    save_dir = Option('-d', type=inputs.Path(type='dir'), default=DEFAULT_DIR, help='Directory to store downloads')
    extension = Option('-e', help='File extension (default: based on mime type)')

    def main(self):
        if not self.save_dir.exists():
            self.save_dir.mkdir(parents=True)

        audio_stream = self.yt.streams.filter(type='audio').order_by('abr')[-1]
        log.info(f'Downloading audio={audio_stream}')

        audio_path = Path(audio_stream.download(output_path=self.save_dir))
        if self.extension:
            path = audio_path.with_suffix(self.extension if self.extension.startswith('.') else f'.{self.extension}')
            audio_path.rename(path)
            audio_path = path

        log.info(f'Saved video to {audio_path}')


def combine_via_ffmpeg(audio_path, video_path, dest_path):
    from subprocess import check_call

    cmd = [
        'ffmpeg',
        '-loglevel', 'warning',
        '-i', audio_path.as_posix(),
        '-i', video_path.as_posix(),
        '-c:v', 'copy',
        # '-c:a', 'aac',
        '-c:a', 'copy',
        '-strict', 'experimental',
        dest_path.as_posix()
    ]
    return check_call(cmd)


if __name__ == '__main__':
    main()
