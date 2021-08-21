"""
LCD Clock numbers

:author: Doug Skrypa
"""

import logging
from datetime import datetime
from math import ceil
from typing import Iterator, Optional

from PIL import Image
from PIL.Image import Image as PILImage
from PIL.ImageDraw import ImageDraw, Draw

from .colors import color_to_rgb, find_unused_color

__all__ = ['SevenSegmentDisplay']
log = logging.getLogger(__name__)
PolygonPoints = tuple[tuple[float, float], ...]


class SevenSegmentDisplay:
    _nums = (0x3f, 0x06, 0x5b, 0x4f, 0x66, 0x6d, 0x7d, 0x07, 0x7f, 0x6f)    # 0-9 with bit order: gfedcba

    def __init__(
        self,
        width: int,
        bar: int = None,
        gap: int = None,
        *,
        corners: bool = True,
        fg: str = '#FF0000',
        bg: str = '#000000',
        bar_pct: float = None,
    ):
        self._bar = None
        self._bar_pct = None
        self.resize(width, bar, gap, bar_pct)
        self.corners = corners
        self.fg = color_to_rgb(fg)
        self.bg = color_to_rgb(bg) if bg else (*find_unused_color([self.fg]), 0)

    def __repr__(self) -> str:
        return (
            f'<{self.__class__.__name__}(width={self.width}, height={self.height}, bar={self.bar},'
            f' bar_pct={self.bar_pct}, gap={self.gap}, corners={self.corners}, fg={self.fg}, bg={self.bg})>'
        )

    # noinspection PyAttributeOutsideInit
    def resize(
        self, width: int = None, bar: int = None, gap: int = None, bar_pct: float = None, preserve_height: bool = False
    ):
        if not (bar is None) ^ (bar_pct is None) and self._bar is None and self._bar_pct is None:
            raise ValueError('One and only one of bar or bar_pct must be provided')
        elif width is None and bar is None and gap is None and bar_pct is None:
            return
        elif width and preserve_height:
            raise ValueError('Cannot preserve height when setting a new width value')
        elif width is None and not hasattr(self, '_width'):
            raise ValueError('Missing required argument: width')
        if bar is not None:
            self._bar_pct = None
            self.bar = bar
        elif bar_pct is not None:
            self.bar_pct = bar_pct
        if width is None:
            width = self.calc_width(self.height) if preserve_height else self._width
        self.width = width
        bar = self._bar
        self.height = 2 * width - bar
        self.gap = gap
        self.seg_height = width - bar

    def calc_width(self, height: float) -> int:
        if bar_pct := self._bar_pct:
            width = ceil(height / (2 - bar_pct))
            if 2 * width - ceil(width * bar_pct) <= height:
                return width
            return width - 1
        elif self._bar:
            return (height + self._bar) // 2

    @property
    def width(self) -> int:
        return self._width

    @width.setter
    def width(self, value: int):
        if self._bar_pct:
            self.bar = ceil(value * self._bar_pct)
        if value < (min_width := self._bar * 4):
            raise ValueError(f'Invalid width={value} < {min_width=} based on bar={self.bar}')
        self._width = value  # noqa

    @property
    def bar(self) -> int:
        return self._bar

    @bar.setter
    def bar(self, value: int):
        if value < 3:
            raise ValueError(f'Invalid bar={value} size - minimum value is 3 px')
        self._bar = value

    @property
    def bar_pct(self) -> Optional[float]:
        return self._bar_pct

    @bar_pct.setter
    def bar_pct(self, value: float):
        if not 0 < value <= 0.25:
            raise ValueError(f'Invalid bar_pct={value:.1%} - must be between 1-25%, inclusive')
        self._bar_pct = value

    @property
    def gap(self) -> int:
        return self._gap

    @gap.setter
    def gap(self, value: int):
        if value is None:
            value = ceil(self.bar / 10)
        if value < 1:
            raise ValueError(f'Invalid gap={value} size (min: 1px)')
        self._gap = value  # noqa

    def time_size(self, seconds: bool = True, width: int = None):
        nums, colons = (6, 2) if seconds else (4, 1)
        spaces = nums + colons - 1
        if width:
            bar = ceil(width * self._bar_pct) if self._bar_pct else self._bar
            height = 2 * width - bar
        else:
            width, height, bar = self._width, self.height, self._bar
        full_width = nums * width + colons * bar + spaces * bar
        return full_width, height

    def draw_time(self, dt: datetime = None, seconds: bool = True) -> PILImage:
        dt = dt or datetime.now()
        image = Image.new('RGBA', self.time_size(seconds), self.bg)
        draw = Draw(image, 'RGBA')  # type: ImageDraw
        ink, fill = draw._getink(None, self.fg)
        draw_polygon = draw.draw.draw_polygon
        colon_offset = self._bar * 2
        num_offset = self._width + self._bar
        x_offset = 0
        nums = (dt.hour, dt.minute, dt.second) if seconds else (dt.hour, dt.minute)
        last = len(nums) - 1
        for i, num in enumerate(nums):
            for n in divmod(num, 10):
                for points in self.num_points(n, x_offset):
                    draw_polygon(points, fill, 1)
                x_offset += num_offset

            if i != last:
                for points in self.colon_points(x_offset):
                    draw_polygon(points, fill, 1)
                x_offset += colon_offset
        return image

    def draw_num(self, num: int) -> PILImage:
        image = Image.new('RGBA', (self._width, self.height), self.bg)
        self._draw_num(num, Draw(image, 'RGBA'))
        return image

    def _draw_num(self, num: int, draw: ImageDraw, x_offset: float = 0, y_offset: float = 0):
        for points in self.num_points(num, x_offset, y_offset):
            draw.polygon(points, fill=self.fg)

    def num_points(self, num: int, x_offset: float = 0, y_offset: float = 0) -> Iterator[PolygonPoints]:
        try:
            segments = self._nums[num]
        except IndexError as e:
            raise ValueError(f'Invalid {num=} - only positive integers between 0-9 (inclusive) are supported') from e
        for seg in (1, 2, 4, 8, 16, 32, 64):
            if seg & segments:
                func = self._vertical_segment if seg & 0x36 else self._horizontal_segment
                yield func(seg, x_offset, y_offset)  # noqa

    def segment_points(self, seg: int, x_offset: float = 0, y_offset: float = 0):
        if seg & 0x36:  # b, c, e, f
            return self._vertical_segment(seg, x_offset, y_offset)
        else:
            return self._horizontal_segment(seg, x_offset, y_offset)

    def _vertical_segment(self, seg: int, x_offset: float = 0, y_offset: float = 0):
        is_bottom = seg & 0x1c
        sh = self.seg_height
        gap = ceil(self.gap / 2)
        bar = self._bar
        is_left = seg & 0x30
        hb = bar / 2
        x0 = x_offset if is_left else (x_offset + self._width - bar)
        x1 = x0 + hb
        x2 = x0 + bar

        y0 = y_offset + (sh if is_bottom else 0) + gap
        in_y1 = y0 + sh - 2 * gap
        mid_y0 = y0 + hb
        mid_y1 = in_y1 + hb
        in_y0 = y0 + bar

        if self.corners:
            if is_bottom:
                y2 = mid_y1 + hb
                yc0, yc1 = (y2, in_y1) if is_left else (in_y1, y2)
                return (x0, yc0), (x2, yc1), (x2, in_y0), (x1, mid_y0), (x0, in_y0)
            else:
                yc0, yc1 = (y0, in_y0) if is_left else (in_y0, y0)
                return (x0, yc0), (x2, yc1), (x2, in_y1), (x1, mid_y1), (x0, in_y1)
        else:
            return (x0, in_y0), (x1, mid_y0), (x2, in_y0), (x2, in_y1), (x1, mid_y1), (x0, in_y1)

    def _horizontal_segment(self, seg: int, x_offset: float = 0, y_offset: float = 0):
        is_g = seg & 0x40
        is_bottom = seg & 0x1c
        gap = ceil(self.gap / 2)
        bar = self._bar
        y0 = y_offset + (self.seg_height * (1 if is_g else 2 if is_bottom else 0))
        y2 = y0 + bar
        x0 = x_offset + gap
        x1 = x_offset + self._width - gap
        in_xl = x0 + bar
        in_xr = x1 - bar
        if self.corners and not is_g:  # segment G never has corners
            yc, yi = (y2, y0) if is_bottom else (y0, y2)
            return (x0, yc), (x1, yc), (in_xr, yi), (in_xl, yi)
        else:
            hb = bar / 2
            mid_xl = x0 + hb
            mid_xr = x1 - hb
            y1 = y0 + hb
            return (in_xl, y0), (mid_xl, y1), (in_xl, y2), (in_xr, y2), (mid_xr, y1), (in_xr, y0)

    def _draw_colon(self, draw: ImageDraw, x_offset: float = 0, y_offset: float = 0):
        for points in self.colon_points(x_offset, y_offset):
            draw.polygon(points, fill=self.fg)

    def colon_points(self, x_offset: float = 0, y_offset: float = 0) -> Iterator[PolygonPoints]:
        bar = self._bar
        sh = self.seg_height
        hb = bar / 2
        x0 = x_offset
        x1 = x0 + bar
        y0 = y_offset + 2 * sh / 3 - hb
        y1 = y0 + bar
        y2 = y_offset + sh + sh / 3 + hb
        y3 = y2 + bar
        yield (x0, y0), (x1, y0), (x1, y1), (x0, y1)
        yield (x0, y2), (x1, y2), (x1, y3), (x0, y3)
