"""
Classes that represent video files and streams within them.

Encoding references:
https://trac.ffmpeg.org/wiki/Encode/AV1
https://trac.ffmpeg.org/wiki/Encode/VP9
https://trac.ffmpeg.org/wiki/Encode/H.265

Notes:
If you get the ``No NVENC capable devices found`` error, you may need to specify a different pixel format, such as
``-profile high444p -pixel_format yuv444p``.  See available formats via ``ffmpeg -h encoder=$encoder``.

Using nvenc decoders/encoders may require downloading additional headers and/or compiling ffmpeg from source - see
https://trac.ffmpeg.org/wiki/HWAccelIntro

:author: Doug Skrypa
"""

import json
import logging
from collections import defaultdict
from fractions import Fraction
from functools import cached_property
from itertools import count
from operator import truediv
from pathlib import Path
from shutil import get_terminal_size
from typing import Union, Any, Type, Iterable

from ..caching.mixins import DictAttrProperty, DictAttrFieldNotFoundError
from ..output.formatting import readable_bytes, format_duration
from ..output.printer import Printer
from .constants import PIXEL_FORMATS_8_BIT, PIXEL_FORMATS_10_BIT
from .ffmpeg import run_ffmpeg_cmd

__all__ = ['Video', 'Stream', 'VideoStream', 'AudioStream', 'SubtitleStream', 'StreamType']
log = logging.getLogger(__name__)

StreamType = Union['Stream', 'VideoStream', 'AudioStream', 'SubtitleStream']


class Video:
    bit_rate: int = DictAttrProperty('info', 'format.bit_rate', type=lambda v: int(v))
    byte_rate: int = DictAttrProperty('info', 'format.bit_rate', type=lambda v: int(v) // 8)
    size: int = DictAttrProperty('info', 'format.size', type=int)
    duration: float = DictAttrProperty('info', 'format.duration', type=float)

    def __init__(self, path: Union[str, Path]):
        self.path = Path(path).expanduser().resolve()

    @cached_property
    def info(self) -> dict[str, Any]:
        # cmd = ['-show_format', '-show_streams', '-of', 'json']
        cmd = ['-show_error', '-find_stream_info', '-show_format', '-show_streams', '-of', 'json']
        output = run_ffmpeg_cmd(cmd, self.path.as_posix(), cmd='ffprobe', capture=True)
        return json.loads(output)

    def filtered_info(self) -> dict[str, dict[str, Any]]:
        return {'format': self.info['format'], 'streams': [s.filtered_info() for s in self.streams]}

    @cached_property
    def streams(self) -> list[StreamType]:
        streams = []
        type_counters = defaultdict(count)
        for index, stream_info in enumerate(self.info['streams']):
            type_index = next(type_counters[stream_info['codec_type']])
            streams.append(Stream.from_dict(stream_info, self, index, type_index))
        return streams

    @cached_property
    def typed_streams(self) -> dict[str, list[StreamType]]:
        typed = {}
        for stream in self.streams:
            typed.setdefault(stream.type, []).append(stream)
        return typed

    def print_info(self, format: str = None, full: bool = False, options: dict[str, bool] = None):  # noqa
        if format:
            Printer(format).pprint(self.info if full else self.filtered_info())
            return

        sections = {'File': self.get_info()}
        sections |= {f'Stream #{i} ({s.type})': s.get_info(options) for i, s in enumerate(self.streams)}

        keys = {k for header, info in sections.items() for k in info}
        max_width = max(map(len, keys)) + 1
        format_row = f'{{:{max_width}s}}  {{}}'.format

        term_width = get_terminal_size().columns - 1
        for header, info in sections.items():
            _print_header(term_width, header)
            for key, val in info.items():
                print(format_row(key + ':', val))

    def get_info(self) -> dict[str, Any]:
        info = self.info['format']
        return {
            'Path': Path(info['filename']).as_posix(),
            'Size': readable_bytes(self.size),
            'Length': format_duration(self.duration),
            'Bit Rate': _rate_str(self.bit_rate),
            'Format': info['format_long_name'],
            'Streams': info['nb_streams'],
        }


class Stream:
    type: str = None  # noqa
    _type_cls_map: dict[str, Type[StreamType]] = {}
    codec: str = DictAttrProperty('info', 'codec_name')

    def __init_subclass__(cls, codec_type: str):  # noqa
        cls.type = codec_type
        cls._type_cls_map[codec_type] = cls

    def __init__(self, info: dict[str, Any], container: 'Video', index: int, type_index: int):
        self.container = container
        self.info = info
        self.index = index
        self.type_index = type_index

    @classmethod
    def from_dict(cls, stream: dict[str, Any], container: 'Video', index: int, type_index: int) -> StreamType:
        codec_type = stream['codec_type']
        try:
            stream_cls = cls._type_cls_map[codec_type]
        except KeyError:
            stream_cls = None
            if codec_type == 'data':
                try:
                    handler = stream['tags']['handler_name']
                except KeyError:
                    pass
                else:
                    if handler == 'SubtitleHandler':
                        stream_cls = cls._type_cls_map['subtitle']

            if stream_cls is None:
                raise ValueError(f'Unexpected {codec_type=} for stream #{index}')

        return stream_cls(stream, container, index, type_index)

    def filtered_info(self) -> dict[str, Any]:
        info = self.info.copy()
        info['disposition'] = {k: v for k, v in info['disposition'].items() if v}
        return info

    @cached_property
    def bit_rate(self) -> int:
        try:
            return int(self.info['bit_rate'])
        except KeyError:
            try:
                return int(self.info['tags']['BPS'])
            except KeyError:
                return 0

    @cached_property
    def byte_rate(self) -> int:
        return self.bit_rate // 8

    def get_info(self, options: dict[str, bool] = None) -> dict[str, Any]:
        return {'Codec': f'{self.codec} ({self.info["codec_long_name"]})', 'Bit Rate': _rate_str(self.bit_rate)}


class VideoStream(Stream, codec_type='video'):
    pixel_format: str = DictAttrProperty('info', 'pix_fmt')
    _aspect_ratio: Fraction = DictAttrProperty('info', 'display_aspect_ratio', lambda v: Fraction(*_ints(v, ':')))

    @cached_property
    def fps(self) -> float:
        a, b = _ints(self.info['avg_frame_rate'], '/')
        try:
            return a // b
        except ZeroDivisionError:
            return 0

    @cached_property
    def aspect_ratio(self) -> Fraction:
        try:
            return self._aspect_ratio
        except DictAttrFieldNotFoundError:
            return Fraction(*self.resolution)

    @cached_property
    def resolution(self) -> tuple[int, int]:
        return int(self.info['width']), int(self.info['height'])

    @cached_property
    def buffer_dimensions(self) -> tuple[int, int]:
        return int(self.info['coded_width']), int(self.info['coded_height'])

    @cached_property
    def bit_depth(self) -> int:
        if self.pixel_format in PIXEL_FORMATS_8_BIT:
            return 8
        elif self.pixel_format in PIXEL_FORMATS_10_BIT:
            return 10
        else:
            raise ValueError(f'Unexpected pixel_format={self.pixel_format!r}')

    @cached_property
    def keyframe_interval_info(self) -> tuple[float, float, float]:
        cmd = [
            '-select_streams', f'v:{self.type_index}',
            '-show_entries', 'packet=pts_time,flags',
            '-of', 'csv=print_section=0',
        ]
        output = run_ffmpeg_cmd(cmd, self.container.path.as_posix(), cmd='ffprobe', capture=True, decode=False)
        times = list(map(float, (line.split(b',', 1)[0] for line in output.splitlines() if b'K' in line)))
        intervals = []
        last = times[0]
        for t in times[1:]:
            intervals.append(t - last)
            last = t
        avg = (sum(intervals) / len(intervals)) if intervals else 0
        return min(intervals), avg, max(intervals)

    def get_info(self, options: dict[str, bool] = None) -> dict[str, Any]:
        info = super().get_info(options)
        info['Bit Depth'] = f'{self.bit_depth} ({self.pixel_format})'
        info['Aspect Ratio'] = '{}:{}'.format(*self.aspect_ratio.as_integer_ratio())
        info['Resolution'] = '{} x {} (buffer: {} x {})'.format(*self.resolution, *self.buffer_dimensions)
        info['FPS'] = f'{self.fps:,.2f}'
        if options and options.get('keyframe_interval'):
            min_int, avg_int, max_int = self.keyframe_interval_info
            min_f = min_int * self.fps
            avg_f = avg_int * self.fps
            max_f = max_int * self.fps
            info['Keyframe Intervals (s)'] = f'min={min_int:.3f} ~ avg={avg_int:.3f} ~ max={max_int:.3f} (seconds)'
            info['Keyframe Intervals (f)'] = f'min={min_f:.3f} ~ avg={avg_f:.3f} ~ max={max_f:.3f} (frames)'
        return info


class AudioStream(Stream, codec_type='audio'):
    channels: int = DictAttrProperty('info', 'channels', type=int)
    sample_rate: int = DictAttrProperty('info', 'sample_rate', type=int)
    bits_per_raw_sample: int = DictAttrProperty('info', 'bits_per_raw_sample', type=int)

    def get_info(self, options: dict[str, bool] = None) -> dict[str, Any]:
        info = super().get_info(options)
        try:
            channel_layout = f' ({self.info["channel_layout"]})'
        except KeyError:
            channel_layout = ''

        info['Channels'] = f'{self.channels}{channel_layout}'
        info['Sample Rate'] = f'{self.sample_rate:,d} Hz'
        info['Bits/Sample (raw)'] = self.bits_per_raw_sample
        return info


class SubtitleStream(Stream, codec_type='subtitle'):
    def get_info(self, options: dict[str, bool] = None) -> dict[str, Any]:
        info = super().get_info(options)
        tags = self.info.get('tags', {})
        found = 0
        for key in ('title', 'language'):
            try:
                val = tags[key]
            except KeyError:
                pass
            else:
                found += 1
                info[key.title()] = val

        if not found:
            log.debug(f'No tag info found for {self}')
        return info


def _print_header(term_width: int, text: str, char: str = '-'):
    width = (term_width - len(text) - 4) // 2
    width = max(width, 4)
    if len(text) % 2 != term_width % 2:
        left = char * width
        right = char * (width + 1)
    else:
        left = right = char * width
    print(f'{left}  {text}  {right}')


def _ints(text: str, delim: str, limit: int = 1) -> Iterable[int]:
    return map(int, text.split(delim, limit))


def _rate_str(bit_rate: int) -> str:
    kbps = bit_rate // 1024
    byte_rate = readable_bytes(bit_rate // 8, rate=True)
    return f'{kbps:,d} kb/s ({byte_rate})'
