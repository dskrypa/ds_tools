"""
:author: Doug Skrypa
"""

import logging
from abc import ABC
from functools import cached_property
from pathlib import Path
from typing import Any, Union, TypeVar

from ...fs.paths import unique_path
from ..constants import (
    NAME_RESOLUTION_MAP, ENCODER_CODEC_MAP, CODEC_DEFAULT_EXT_MAP, ENCODER_PIXEL_FORMATS, PIXEL_FORMATS_8_BIT
)
from ..exceptions import FfmpegError
from ..ffmpeg import run_ffmpeg_cmd, get_decoders
from ..videos import Video, VideoStream

__all__ = ['Encoder']
log = logging.getLogger(__name__)

EncoderType = TypeVar('EncoderType', bound='Encoder')


class Encoder(ABC):
    _codec_encoder_cls_map = {}
    codec: str
    encoders: tuple[str, ...]
    default_encoder: str

    def __init_subclass__(cls, codec: str, default_encoder: str = None):  # noqa
        cls._codec_encoder_cls_map[codec] = cls
        cls.codec = codec
        cls.encoders = tuple(encoder for encoder, e in ENCODER_CODEC_MAP.items() if e == codec)
        if default_encoder:
            cls.default_encoder = default_encoder
        else:
            cls.default_encoder = cls.encoders[0]

    def __init__(self, video: Video, v_stream: VideoStream = None, options: dict[str, Any] = None, encoder: str = None):
        self.video = video
        self.options = options or {}
        self.encoder = encoder or self.default_encoder
        try:
            self.v_stream = v_stream or next(s for s in video.typed_streams['video'])
        except StopIteration:
            raise ValueError(
                f'Unable to find a video stream in {video} - a specific stream must be selected / provided'
            ) from None

    @classmethod
    def for_encoding(
        cls,
        codec: str,
        video: Video,
        v_stream: VideoStream = None,
        options: dict[str, Any] = None,
        encoder: str = None,
        **kwargs,
    ) -> EncoderType:
        try:
            enc_cls = cls._codec_encoder_cls_map[codec]
        except KeyError:
            raise ValueError(f'No Encoder subclass has been registered for {codec=}') from None
        return enc_cls(video=video, v_stream=v_stream, options=options, encoder=encoder, **kwargs)

    def __repr__(self) -> str:
        return f'<{self.__class__.__name__}[{self.codec}:{self.encoder}]{self.options}>'

    @cached_property
    def pixel_formats(self) -> set[str]:
        return ENCODER_PIXEL_FORMATS[self.encoder]

    @cached_property
    def new_resolution(self) -> tuple[int, int]:
        if new_res := self.options.get('resolution'):
            if isinstance(new_res, str):
                width, height = NAME_RESOLUTION_MAP[new_res]
                aspect_ratio = self.v_stream.aspect_ratio.as_integer_ratio()
                if aspect_ratio != (16, 9):
                    height = width * aspect_ratio[1] // aspect_ratio[0]
            else:
                try:
                    width, height = new_res  # noqa
                except Exception as e:
                    raise TypeError(f'Invalid resolution={new_res!r} - expected str like 1080p or tuple of ints') from e
                else:
                    if not (isinstance(width, int) and isinstance(height, int)):
                        raise TypeError(f'Invalid resolution={new_res!r} - expected str like 1080p or tuple of ints')

            return width, height
        else:
            return self.v_stream.resolution

    @cached_property
    def new_fps(self) -> float:
        if new_fps := self.options.get('fps'):
            return new_fps
        return self.v_stream.fps

    def get_pix_fmt_args(self) -> list[str]:
        if pixel_format := self.options.get('pixel_format'):
            return ['-pix_fmt', pixel_format]

        stream = self.v_stream
        if self.new_resolution[1] > 1080 or stream.bit_depth == 8:
            return []

        old_px_fmt = stream.pixel_format
        candidates = self.pixel_formats.intersection(PIXEL_FORMATS_8_BIT)
        if len(candidates) == 1:
            new_px_fmt = next(iter(candidates))
        else:
            candidates = {f for f in candidates if f.startswith(old_px_fmt)}
            if len(candidates) == 1:
                new_px_fmt = next(iter(candidates))
            else:
                log.warning(
                    f'Unable to automatically pick a new pixel format from {candidates=} - defaulting to original:'
                    f' {old_px_fmt}'
                )
                return []

        return ['-pix_fmt', new_px_fmt]

    def get_input_args(self) -> list[str]:
        args = []
        if in_hw_accel_dev := self.options.get('in_hw_accel_dev'):  # use specific gpu
            args += ['-hwaccel_device', in_hw_accel_dev]
        if in_hw_accel := self.options.get('in_hw_accel'):
            args += ['-hwaccel', 'cuda' if in_hw_accel is True else in_hw_accel]
        if in_codec := self.options.get('in_codec'):
            if in_codec is True:
                decoders = [
                    d for d in get_decoders(True).get(self.v_stream.codec, {}).values()
                    if 'Nvidia CUVID' in d.description
                ]
                if len(decoders) == 1:
                    in_codec = decoders[0].name
                else:
                    raise ValueError(
                        f'Unable to automatically determine the in_codec to use - it must be explicitly specified'
                    )

            args += ['-c:v', in_codec]
        if in_hw_accel_out_fmt := self.options.get('in_hw_accel_out_fmt'):
            args += ['-hwaccel_output_format', in_hw_accel_out_fmt]
        args += ['-i', self.video.path.as_posix()]
        return args

    def get_args(self, audio: str = None, pass_num: int = None) -> list[str]:
        args = self.get_input_args() + ['-c:v', self.encoder]
        if audio:
            args += ['-c:a', audio]
        if self.video.typed_streams.get('subtitle'):
            args += ['-c:s', 'copy']
        if self.new_resolution != self.v_stream.resolution:
            args += ['-vf', 'scale={}x{}'.format(*self.new_resolution)]
        if self.new_fps != self.v_stream.fps:
            args += ['-vf', f'fps={self.new_fps}']
        args += self.get_pix_fmt_args()
        return args

    def pick_out_path(self, out_path: Union[str, Path, None]) -> Path:
        if out_path:
            out_path = Path(out_path).expanduser()
            if out_path.is_dir():
                out_dir, stem, ext = out_path, self.video.path.stem, CODEC_DEFAULT_EXT_MAP[self.codec]
            elif not out_path.exists():
                return out_path
            else:
                stem, ext = out_path.name.rsplit('.', 1)
                out_dir = out_path.parent
        else:
            out_dir, stem, ext = self.video.path.parent, self.video.path.stem, CODEC_DEFAULT_EXT_MAP[self.codec]

        return unique_path(out_dir, stem, '.' + ext, add_date=False)

    def encode(self, out_path: Union[str, Path] = None, passes: int = 1):
        if passes not in (1, 2):
            raise ValueError(f'Invalid {passes=} value - must be 1 or 2')

        out_path = self.pick_out_path(out_path)
        if passes == 1:
            try:
                run_ffmpeg_cmd(self.get_args(audio='copy'), out_path, log_level=logging.INFO)
            except FfmpegError:
                if out_path.exists() and out_path.stat().st_size == 0:
                    out_path.unlink()
                raise
        else:
            null_path = '/dev/null' if Path('/dev/null').exists() else 'NUL'  # assume Windows if no /dev/null
            pass_1 = self.get_args(pass_num=1) + ['-pass', '1', '-an', '-f', 'null']
            pass_2 = self.get_args(pass_num=2) + ['-pass', '2', '-c:a', 'copy']
            run_ffmpeg_cmd(pass_1, null_path, log_level=logging.INFO)
            try:
                run_ffmpeg_cmd(pass_2, out_path, log_level=logging.INFO)
            except FfmpegError:
                if out_path.exists() and out_path.stat().st_size == 0:
                    out_path.unlink()
                raise
