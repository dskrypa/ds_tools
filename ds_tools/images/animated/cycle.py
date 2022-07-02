"""
Utilities for working with animated gif images

:author: Doug Skrypa
"""

from __future__ import annotations

import logging
from pathlib import Path
from tkinter import PhotoImage
from typing import Iterator, Iterable, Callable, Union, TypeVar, Generic

from PIL.Image import Image as PILImage
from PIL.ImageSequence import Iterator as FrameIterator
from PIL.ImageTk import PhotoImage as PilPhotoImage

from ..utils import as_image

__all__ = ['FrameCycle', 'PhotoImageCycle']
log = logging.getLogger(__name__)

T_co = TypeVar('T_co', covariant=True)


class FrameCycle(Generic[T_co]):
    __slots__ = ('n', '_frames', '_wrapper', '_duration', '_default_duration', '_frames_and_durations', 'first_delay')

    def __init__(
        self,
        frames: Iterable[PILImage],
        wrapper: Callable[[PILImage], T_co] = None,
        duration: int = None,
        default_duration: int = 100,
    ):
        self.n = 0
        self._frames = tuple(frames)
        self._wrapper = wrapper
        self._duration = duration
        self._default_duration = default_duration

        def get_duration(f):
            return duration if duration is not None else f.info.get('duration', default_duration)

        if wrapper is None:
            self._frames_and_durations = tuple((f, get_duration(f)) for f in self._frames)
        else:
            self._frames_and_durations = tuple((wrapper(f), get_duration(f)) for f in self._frames)

        self.first_delay = self._frames_and_durations[0][1]

    def __len__(self) -> int:
        return len(self._frames_and_durations)

    def __iter__(self) -> Iterator[tuple[T_co, int]]:
        return self

    def __next__(self) -> tuple[T_co, int]:
        self.n += 1
        try:
            return self._frames_and_durations[self.n]
        except IndexError:
            self.n = 0
            return self._frames_and_durations[0]

    next = __next__

    def back(self) -> tuple[T_co, int]:
        self.n -= 1
        if self.n < 0:
            self.n = len(self._frames_and_durations) - 1
        return self._frames_and_durations[self.n]

    @property
    def current_image(self) -> PILImage:
        return self._frames[self.n]

    @property
    def current_frame(self) -> T_co:
        return self._frames_and_durations[self.n][0]

    def resized(self, width: int, height: int) -> FrameCycle[PilPhotoImage]:
        size = (width, height)
        frames = [frame.copy().resize(size) for frame in self._frames]
        return FrameCycle(frames, PilPhotoImage, self._duration, self._default_duration)


class PhotoImageCycle(FrameCycle[PhotoImage]):
    __slots__ = ('path', '_pi_frames')

    def __init__(self, path: Union[Path, str], duration: int = None, default_duration: int = 100):  # noqa
        self.path = Path(path).expanduser()
        self.n = 0
        image = as_image(self.path)
        self._pi_frames = tuple(
            PhotoImage(file=path.as_posix(), format=f'gif -index {n}') for n in range(image.n_frames)
        )
        self._frames = tuple(FrameIterator(image))
        self._wrapper = PhotoImage
        self._duration = duration
        self._default_duration = default_duration

        def get_duration(f):
            return duration if duration is not None else f.info.get('duration', default_duration)

        self._frames_and_durations = tuple((pi, get_duration(f)) for pi, f in zip(self._pi_frames, self._frames))
        self.first_delay = self._frames_and_durations[0][1]
