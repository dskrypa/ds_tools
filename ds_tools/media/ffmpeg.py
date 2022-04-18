"""
Utilities for interacting with ffmpeg.

:author: Doug Skrypa
"""

import json
import logging
import re
from pathlib import Path
from subprocess import run, CalledProcessError
from typing import Union, Optional, Sequence, Any

from .constants import FFMPEG_CONFIG_PATH
from .exceptions import FfmpegError

__all__ = ['load_config', 'set_ffmpeg_path', 'run_ffmpeg_cmd', 'get_decoders', 'get_encoders', 'CodecLibrary']
log = logging.getLogger(__name__)

FFMPEG_DIR: Optional[Path] = None


def set_ffmpeg_path(path: Union[str, Path, None]):
    global FFMPEG_DIR

    if path is None:
        FFMPEG_DIR = None
        return

    path = Path(path).expanduser().resolve()
    if path.is_file():
        path = path.parent

    FFMPEG_DIR = path


def load_config(path: Union[str, Path] = None):
    path = Path(path or FFMPEG_CONFIG_PATH).expanduser()
    if not path.exists():
        return

    config = json.loads(path.read_text('utf-8'))
    if ffmpeg_path := config.get('ffmpeg_path'):
        set_ffmpeg_path(ffmpeg_path)


def run_ffmpeg_cmd(
    args: Sequence[str] = None,
    file: Union[str, Path] = None,
    cmd: str = 'ffmpeg',
    capture: bool = False,
    kwargs: dict[str, Any] = None,
    log_level: int = logging.DEBUG,
) -> Optional[str]:
    command = [FFMPEG_DIR.joinpath(cmd).as_posix() if FFMPEG_DIR is not None else cmd]
    if args:
        command.extend(args)
    if kwargs:
        command.extend(kwargs_to_cli_args(kwargs))
    if file is not None:
        command.append(file.as_posix() if isinstance(file, Path) else file)

    log.log(log_level, f'Running command: {command}')
    try:
        results = run(command, capture_output=capture, check=True)
    except CalledProcessError as e:
        raise FfmpegError(command, 'Command did not complete successfully') from e
    else:
        return results.stdout.decode('utf-8') if capture else None


def kwargs_to_cli_args(kwargs: dict[str, Any]) -> list[str]:
    args = []
    for k, v in sorted(kwargs.items()):
        args.append(f'-{k}')
        if v is not None:
            args.append(str(v))
    return args


class CodecLibrary:
    _codec_match = re.compile(r'^(.*?) \(codec (.+)\)$').match
    __slots__ = ('capabilities', 'name', 'description', 'codec')

    def __init__(self, info: str):
        capabilities, self.name, description = info.split(maxsplit=2)
        self.capabilities = capabilities.replace('.', '')
        if m := self._codec_match(description):
            self.description, self.codec = m.groups()
        else:
            self.description = description
            self.codec = None

    def __repr__(self) -> str:
        parts = [self.name, f'({self.description})']
        if self.codec:
            parts.append(f'codec={self.codec}')
        parts.append(f'capabilities={self.capabilities}')
        info = ', '.join(parts)
        return f'<{self.__class__.__name__}[{info}]>'

    @property
    def video(self) -> bool:
        return 'V' in self.capabilities

    @property
    def audio(self) -> bool:
        return 'A' in self.capabilities

    @property
    def subtitle(self) -> bool:
        return 'S' in self.capabilities


def get_encoders(by_codec: bool = False) -> dict[str, Union[CodecLibrary, dict[Optional[str], CodecLibrary]]]:
    return _get_codec_libs('-encoders', by_codec)


def get_decoders(by_codec: bool = False) -> dict[str, Union[CodecLibrary, dict[Optional[str], CodecLibrary]]]:
    return _get_codec_libs('-decoders', by_codec)


def _get_codec_libs(
    lib_type: str, by_codec: bool = False
) -> dict[str, Union[CodecLibrary, dict[Optional[str], CodecLibrary]]]:
    stdout = run_ffmpeg_cmd([lib_type], capture=True)
    """
    Example format:
    Decoders:
     V..... = Video
    ...
     .....D = Supports direct rendering method 1
     ------
     V....D 012v                 Uncompressed 4:2:2 10-bit
     V....D 4xm                  4X Movie
    ...
    """
    lines = iter(map(str.strip, stdout.splitlines()[1:]))
    while '=' in next(lines):  # This will also consume the ------
        pass

    if by_codec:
        codec_name_lib_map = {}
        for d in map(CodecLibrary, lines):
            codec_name_lib_map.setdefault(d.codec, {})[d.name] = d
        return codec_name_lib_map
    else:
        return {d.name: d for d in map(CodecLibrary, lines)}
