"""
Utilities for working with animated gif images

:author: Doug Skrypa
"""

import logging
from functools import cached_property
from pathlib import Path
from typing import Union, Iterator, Iterable, Sequence, Callable

from PIL import Image
from PIL.Image import Image as PILImage
from PIL.ImagePalette import ImagePalette
from PIL.ImageSequence import Iterator as FrameIterator

from .utils import ImageType, Size, Box, as_image, color_to_alpha

__all__ = ['AnimatedGif']
log = logging.getLogger(__name__)


class AnimatedGif:
    """
    Notes:
        tile = (decoder, (x0, y0, x1, y1), frame_byte_offset, (bits, interlace, transparency))
    """
    def __init__(self, image: Union[ImageType, Iterable[ImageType]]):
        try:
            image = as_image(image)
        except (TypeError, ValueError):
            self._image = None
            self._frames = tuple(map(as_image, image))
        else:
            if image.format != 'GIF':
                raise ValueError(f'Unsupported image format={image.format!r} for {image=} - it is not a GIF')
            self._image = image
            self._frames = None

    @cached_property
    def info(self):
        return self._image.info if self._image else self._frames[0].info

    @cached_property
    def n_frames(self):
        return len(self._frames) if self._frames is not None else self._image.n_frames

    @classmethod
    def from_images(cls, images: Union[Iterable[ImageType], str, Path]) -> 'AnimatedGif':
        if isinstance(images, (str, Path)):
            path = Path(images).expanduser()
            if not path.is_dir():
                raise ValueError(f'Cannot create animated gif - path={path.as_posix()!r} is not a directory')
            images = path.iterdir()
        return cls(images)

    def frames(self, copy: bool = False) -> Iterator[PILImage]:
        frame_iter = self._frames if self._frames is not None else FrameIterator(self._image)
        if copy:
            for frame in frame_iter:
                yield frame.copy()
        else:
            yield from frame_iter

    def color_to_alpha(self, color: str) -> 'AnimatedGif':
        return self.__class__((color_to_alpha(frame, color) for frame in self.frames(True)))

    def resize(self, size: Size, resample: int = Image.ANTIALIAS, box: Box = None, reducing_gap: float = None):
        frames = (
            frame.resize(size, resample=resample, box=box, reducing_gap=reducing_gap)
            for frame in self.frames(True)
        )
        return self.__class__(frames)

    def cycle(self, wrapper: Callable = None, duration: int = None, default_duration: int = 100) -> 'FrameCycle':
        return FrameCycle(self.frames(), wrapper, duration, default_duration)

    def get_info(self, frames: bool = False):
        if frames:
            return list(map(_frame_info, self.frames()))
        else:
            image = self._image or self._frames[0]
            return _frame_info(image)

    def save_frames(self, path: Union[Path, str], prefix: str = 'frame_', format: str = 'PNG', mode: str = None):  # noqa
        path = Path(path).expanduser().resolve() if isinstance(path, str) else path
        if path.exists():
            if not path.is_dir():
                raise ValueError(f'Invalid path={path.as_posix()!r} - it must be a directory')
        else:
            path.mkdir(parents=True)

        name_fmt = prefix + '{:0' + str(len(str(self.n_frames))) + 'd}.' + format.lower()
        for i, frame in enumerate(self.frames()):
            if mode and mode != frame.mode:
                frame = frame.convert(mode=mode)
            frame_path = path.joinpath(name_fmt.format(i))
            log.info(f'Saving {frame_path.as_posix()}')
            with frame_path.open('wb') as f:
                frame.save(f, format=format)

    def save(
        self,
        path: Union[Path, str],
        *,
        include_color_table: bool = None,
        interlace: bool = None,
        disposal: Union[int, Sequence[int]] = None,
        palette: Union[bytes, ImagePalette] = None,
        optimize: bool = None,
        transparency: int = None,
        duration: Union[int, Sequence[int]] = None,
        loop: int = 0,
        comment: str = None,
    ):
        """
        Parameters copied from: https://pillow.readthedocs.io/en/stable/handbook/image-file-formats.html#saving

        All parameters will use default values from the original image's info dict, if present.

        :param path: Output path
        :param include_color_table: Whether or not to include local color table
        :param interlace: Whether or not the image is interlaced
        :param disposal: The way to treat the graphic after displaying it. Specify an int for constant disposal, or a
          list/tuple containing per-frame values.  Accepted values:\n
            - 0: No disposal specified
            - 1: Do not dispose
            - 2: Restore to background color
            - 3: Restore to previous content
        :param palette: Use the specified palette.  May be an :class:`ImagePalette` object or a bytes/bytearray
          containing palette entries in RGBRGB... format, with no more than 768 bytes.
        :param optimize: If a palette is present, attempt to compress it by eliminating unused colors. Only useful if
          the palette can be compressed to the next smaller of power of 2 elements.
        :param transparency: Transparency as a value between 0 (100% transparency) and 255 (0% transparency)
        :param duration: Display duration for each frame in milliseconds. Specify an int for constant duration, or a
          list/tuple containing per-frame values.
        :param loop: Number of times to loop; 0 = loop forever.
        :param comment: Comment about the image
        """
        path = Path(path).expanduser().resolve() if isinstance(path, str) else path
        keys = (
            'include_color_table', 'interlace', 'disposal', 'palette', 'optimize', 'transparency', 'duration', 'loop',
            'comment'
        )
        values = (include_color_table, interlace, disposal, palette, optimize, transparency, duration, loop, comment)
        kwargs = {key: val for key, val in zip(keys, values) if val is not None}

        frames = iter(self.frames())
        frame = next(frames)
        log.info(f'Saving {path.as_posix()}')
        with path.open('wb') as f:
            frame.save(f, save_all=True, append_images=frames, **kwargs)


class FrameCycle:
    def __init__(
        self,
        frames: Iterable[PILImage],
        wrapper: Callable = None,
        duration: int = None,
        default_duration: int = 100,
    ):
        self.n = 0
        wrapper = wrapper if wrapper is not None else lambda f: f

        def get_duration(f):
            return duration if duration is not None else f.info.get('duration', default_duration)

        self._frames_and_durations = tuple((wrapper(f), get_duration(f)) for f in frames)
        self.first_delay = self._frames_and_durations[0][1]

    def __len__(self):
        return len(self._frames_and_durations)

    def __iter__(self):
        return self

    def __next__(self):
        self.n += 1
        try:
            return self._frames_and_durations[self.n]
        except IndexError:
            self.n = 0
            return self._frames_and_durations[0]

    next = __next__

    def back(self):
        self.n -= 1
        if self.n < 0:
            self.n = len(self._frames_and_durations) - 1
        return self._frames_and_durations[self.n]


def _frame_info(frame: PILImage):
    base_info = frame.info
    info = {key: base_info.get(key) for key in ('background', 'duration', 'loop', 'transparency', 'extension')}
    attrs = ('disposal_method', 'disposal', 'dispose_extent', 'tile')
    info.update((attr, getattr(frame, attr, None)) for attr in attrs)
    if palette := frame.palette:
        info['palette'] = f'<ImagePalette[mode={palette.mode!r}, raw={palette.rawmode}, len={len(palette.palette)}]>'

    return info