#!/usr/bin/env python
# PYTHON_ARGCOMPLETE_OK

import sys
from pathlib import Path

sys.path.insert(0, Path(__file__).resolve().parents[1].joinpath('bin').as_posix())
import _venv  # This will activate the venv, if it exists and is not already active

import logging

from ds_tools.argparsing import ArgParser

log = logging.getLogger(__name__)


def parser():
    parser = ArgParser(description='Download YouTube videos')

    dl_parser = parser.add_subparser('action', 'dl', 'Download a video from YouTube')
    dl_parser.add_argument('url', metavar='URL', help='The name URL of the video to download')
    dl_parser.add_argument('--save_dir', '-d', metavar='PATH', default='~/Downloads/youtube/', help='Directory to store downloads')
    dl_parser.add_argument('--resolution', '-r', default='1080p', help='Video resolution (default: %(default)s)')
    dl_parser.add_argument('--extension', '-e', default='mp4', help='Video extension')

    list_parser = parser.add_subparser('action', 'list', 'List available parts for the given YouTube video')
    list_parser.add_argument('url', help='The name URL of the video to download')

    audio_parser = parser.add_subparser('action', 'audio', 'Download audio from YouTube')
    audio_parser.add_argument('url', help='The name URL of the video to download')
    audio_parser.add_argument('--save_dir', '-d', default='~/Downloads/youtube/', help='Directory to store downloads')
    audio_parser.add_argument('--extension', '-e', help='File extension (default: based on mime type)')

    parser.include_common_args('verbosity')
    return parser


def main():
    args = parser().parse_args(req_subparser_value=True)

    from ds_tools.logging import init_logging
    init_logging(args.verbose, log_path=None)

    from pathlib import Path
    from pytube import YouTube

    yt = YouTube(args.url)
    if args.action == 'dl':
        from tempfile import TemporaryDirectory

        dest_dir = Path(args.save_dir).expanduser()
        if not dest_dir.exists():
            dest_dir.mkdir(parents=True)

        with TemporaryDirectory() as tmp_dir:
            vid_stream = yt.streams.filter(file_extension=args.extension, res=args.resolution).order_by('resolution')[-1]
            log.info(f'Downloading video={vid_stream}')
            vid_path = Path(vid_stream.download(output_path=tmp_dir))

            audio_stream = yt.streams.filter(type='audio').order_by('abr')[-1]
            log.info(f'Downloading audio={audio_stream}')
            audio_path = Path(audio_stream.download(output_path=tmp_dir))

            dest_path = dest_dir.joinpath(vid_stream.default_filename)
            combine_via_ffmpeg(audio_path, vid_path, dest_path)
            log.info(f'Saved video to {dest_path}')
    elif args.action == 'list':
        print('Video:')
        for stream in yt.streams.filter(type='video').order_by('resolution'):
            print(f'    {stream}')

        print('\nAudio:')
        for stream in yt.streams.filter(type='audio').order_by('abr'):
            print(f'    {stream}')
    elif args.action == 'audio':
        dest_dir = Path(args.save_dir).expanduser()
        if not dest_dir.exists():
            dest_dir.mkdir(parents=True)
        audio_stream = yt.streams.filter(type='audio').order_by('abr')[-1]
        log.info(f'Downloading audio={audio_stream}')
        audio_path = Path(audio_stream.download(output_path=dest_dir))
        if args.extension:
            path = audio_path.with_suffix(args.extension if args.extension.startswith('.') else f'.{args.extension}')
            audio_path.rename(path)
            audio_path = path
        log.info(f'Saved video to {audio_path}')
    else:
        raise ValueError(f'Unknown action={args.action}')


def combine_via_ffmpeg(audio_path, video_path, dest_path):
    from ds_tools.shell import exec_local

    cmd = [
        'ffmpeg',
        '-loglevel', 'warning',
        '-i', audio_path.as_posix(),
        '-i', video_path.as_posix(),
        '-c:v', 'copy',
        '-c:a', 'aac',
        '-strict', 'experimental',
        dest_path.as_posix()
    ]
    return exec_local(*cmd, mode='raw', raise_nonzero=True)


if __name__ == '__main__':
    main()
