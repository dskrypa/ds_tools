"""
Utilities for working with animated gif images

:author: Doug Skrypa
"""

import logging
from pathlib import Path
from tkinter import PhotoImage
from typing import Iterable, Callable, Union

from PIL.Image import Image as PILImage
from PIL.ImageSequence import Iterator as FrameIterator

from ..utils import as_image

__all__ = ['FrameCycle', 'PhotoImageCycle']
log = logging.getLogger(__name__)


class FrameCycle:
    def __init__(
        self,
        frames: Iterable[PILImage],
        wrapper: Callable = None,
        duration: int = None,
        default_duration: int = 100,
    ):
        self.n = 0
        self._frames = tuple(frames) if wrapper is not None else None
        wrapper = wrapper if wrapper is not None else lambda f: f

        def get_duration(f):
            return duration if duration is not None else f.info.get('duration', default_duration)

        self._frames_and_durations = tuple((wrapper(f), get_duration(f)) for f in self._frames)
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

    @property
    def current_image(self) -> PILImage:
        if self._frames is not None:
            return self._frames[self.n]
        return self._frames_and_durations[self.n][0]


class PhotoImageCycle(FrameCycle):
    # noinspection PyMissingConstructor
    def __init__(self, path: Union[Path, str], duration: int = None, default_duration: int = 100):
        self.path = Path(path).expanduser()
        self.n = 0
        image = as_image(self.path)
        self._pi_frames = tuple(
            PhotoImage(file=path.as_posix(), format=f'gif -index {n}') for n in range(image.n_frames)
        )
        self._frames = tuple(FrameIterator(image))

        def get_duration(f):
            return duration if duration is not None else f.info.get('duration', default_duration)

        self._frames_and_durations = tuple((pi, get_duration(f)) for pi, f in zip(self._pi_frames, self._frames))
        self.first_delay = self._frames_and_durations[0][1]

    @property
    def current_image(self) -> PILImage:
        return self._frames[self.n]
