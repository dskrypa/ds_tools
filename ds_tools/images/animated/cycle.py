"""
Utilities for working with animated gif images

:author: Doug Skrypa
"""

import logging
from typing import Iterable, Callable

from PIL.Image import Image as PILImage

__all__ = ['FrameCycle']
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
