"""
LCD Clock numbers

:author: Doug Skrypa
"""

import logging
from datetime import datetime
from math import ceil
from typing import Union, Iterator

from PIL import Image
from PIL.Image import Image as PILImage
from PIL.ImageDraw import ImageDraw, Draw

from .colors import color_to_rgb, find_unused_color

__all__ = []
log = logging.getLogger(__name__)

NUM_CELL_MAP = {
    0: ('top_center', 'top_left', 'top_right', 'low_left', 'low_right', 'low_center'),
    1: ('top_right', 'low_right'),
    2: ('top_center', 'top_right', 'mid_center', 'low_left', 'low_center'),
    3: ('top_center', 'top_right', 'mid_center', 'low_right', 'low_center'),
    4: ('top_left', 'top_right', 'mid_center', 'low_right'),
    5: ('top_center', 'top_left', 'mid_center', 'low_right', 'low_center'),
    6: ('top_center', 'top_left', 'mid_center', 'low_left', 'low_right', 'low_center'),
    7: ('top_center', 'top_right', 'low_right'),
    8: ('top_center', 'top_left', 'top_right', 'mid_center', 'low_left', 'low_right', 'low_center'),
    9: ('top_center', 'top_left', 'top_right', 'mid_center', 'low_right'),
}


class LCDClock:
    def __init__(self, char_width: int, color: str = '#FF0000', bg: str = '#000000', slim: bool = False):
        self.rgb = color_to_rgb(color)
        self.char_size = (char_width, char_width * 7 // 4)  # width, height
        self.bg = color_to_rgb(bg) if bg else (*find_unused_color([self.rgb]), 0)
        self.slim = slim

    @classmethod
    def time_size(cls, char_width: int, seconds: bool = True):
        height = char_width * 7 // 4
        x = char_width // 4
        full_width = char_width * (6 if seconds else 4) + x * (9 if seconds else 5)
        return full_width, height

    def draw_time(self, dt: datetime, seconds: bool = True) -> PILImage:
        width, height = self.char_size
        x = width // 4
        ndx = x * 5
        image = Image.new('RGBA', (self.time_size(width, seconds)[0], height), self.bg)
        draw = Draw(image, 'RGBA')  # type: ImageDraw
        for i, h in enumerate(divmod(dt.hour, 10)):
            self._draw_num(h, draw, ndx * i)
        x_offset = x * 10
        self._draw_colon(draw, x_offset)
        x_offset += x * 2
        for i, m in enumerate(divmod(dt.minute, 10)):
            self._draw_num(m, draw, x_offset + ndx * i)
        if seconds:
            x_offset += ndx * 2
            self._draw_colon(draw, x_offset)
            x_offset += x * 2
            for i, m in enumerate(divmod(dt.second, 10)):
                self._draw_num(m, draw, x_offset + ndx * i)
        return image

    def draw_all(self) -> dict[Union[str, int], PILImage]:
        images = {n: self.draw_num(n) for n in range(10)}
        images[':'] = self.draw_colon()
        return images

    def draw_colon(self):
        width, height = self.char_size
        x = width // 4
        image = Image.new('RGBA', (x, height), self.bg)
        draw = Draw(image, 'RGBA')  # type: ImageDraw
        self._draw_colon(draw)
        return image

    def draw_num(self, num: int) -> PILImage:
        if not (0 <= num <= 9):
            raise ValueError('Only positive integers between 0-9 (inclusive) are supported')
        image = Image.new('RGBA', self.char_size, self.bg)
        self._draw_num(num, Draw(image, 'RGBA'))
        return image

    def _draw_num(self, num: int, draw: ImageDraw, x_offset: float = 0, y_offset: float = 0):
        cell_points = num_cell_points(*self.char_size, x0=x_offset, y0=y_offset, slim=self.slim)
        for cell in NUM_CELL_MAP[num]:
            draw.polygon(cell_points[cell], fill=self.rgb)

    def _colon_points(self, c_offset: int, x_offset: float = 0, y_offset: float = 0):
        width, height = self.char_size
        xu, yu = (8, 14) if self.slim else (4, 7)
        x = width / xu
        y = height / yu
        x_mults = (0.5, 1.5, 1.5, 0.5) if self.slim else (0, 1, 1, 0)
        if self.slim:
            c_offset = c_offset * 2 + 2
        y_mults = (c_offset + 1.5, c_offset + 1.5, c_offset + 2.5, c_offset + 2.5)
        for x_mult, y_mult in zip(x_mults, y_mults):
            yield x_offset + x * x_mult, y_offset + y * y_mult

    def _draw_colon(self, draw: ImageDraw, x_offset: float = 0, y_offset: float = 0):
        for c_offset in (0, 3):
            draw.polygon(list(self._colon_points(c_offset, x_offset, y_offset)), fill=self.rgb)

    def draw_cell(self, cell: str):
        image = Image.new('RGBA', self.char_size, self.bg)
        draw = Draw(image, 'RGBA')  # type: ImageDraw
        draw.polygon(num_cell_points(*self.char_size, slim=self.slim)[cell], fill=self.rgb)
        return image


def draw_num(num: int, char_width: int, **kwargs) -> PILImage:
    return LCDClock(char_width, **kwargs).draw_num(num)


def draw_cell(cell: str, char_width: int, **kwargs) -> PILImage:
    return LCDClock(char_width, **kwargs).draw_cell(cell)


def draw_time(dt: datetime = None, seconds: bool = True, char_width: int = 40, **kwargs) -> PILImage:
    return LCDClock(char_width, **kwargs).draw_time(dt or datetime.now(), seconds)


def num_cell_points(width: int, height: int, x0: float = 0, y0: float = 0, slim: bool = False):
    cell_points = _num_cell_points(width, height, slim)
    if x0 == y0 == 0:
        return cell_points
    return {name: [(x + x0, y + y0) for x, y in points] for name, points in cell_points.items()}


def _num_cell_points(width: int, height: int, slim: bool = False):
    # Delta/offset to add separation between cells
    d = 2 if width < 80 else 3 if width < 400 else 4
    out_w, out_n = 0, 0
    out_e, out_s = width, height
    xu, yu = (8, 14) if slim else (4, 7)
    in_w = x = width / xu
    in_n = y = height / yu
    in_e = x * (xu - 1)
    in_s = y * (yu - 1)
    mw = x / 2
    me = x * (xu - 0.5)
    mid_c = height / 2
    mn = mid_c - y / 2
    ms = mid_c + y / 2
    return {
        'top_center': [(out_w + d, out_n), (out_e - d, out_n), (in_e - d, in_n), (in_w + d, in_n)],
        'top_left': [(out_w, out_n + d), (in_w, in_n + d), (in_w, mn - d), (mw, mid_c - d), (out_w, mn - d)],
        'top_right': [(out_e, out_n + d), (out_e, mn - d), (me, mid_c - d), (in_e, mn - d), (in_e, in_n + d)],
        'mid_center': [
            (mw + d, mid_c), (in_w + d, mn), (in_e - d, mn), (me - d, mid_c), (in_e - d, ms), (in_w + d, ms)
        ],
        'low_left': [(mw, mid_c + d), (in_w, ms + d), (in_w, in_s - d), (out_w, out_s - d), (out_w, ms + d)],
        'low_right': [(me, mid_c + d), (out_e, ms + d), (out_e, out_s - d), (in_e, in_s - d), (in_e, ms + d)],
        'low_center': [(in_w + d, in_s), (in_e - d, in_s), (out_e - d, out_s), (out_w + d, out_s)],
    }


# =====================================================================================================================

PolygonPoints = tuple[tuple[float, float], ...]


class SevenSegmentDisplay:
    _nums = (0x3f, 0x06, 0x5b, 0x4f, 0x66, 0x6d, 0x7d, 0x07, 0x7f, 0x6f)    # 0-9 with bit order: gfedcba
    _bits = tuple(1 << i for i in range(7))                                 # abcdefg

    def __init__(
        self,
        width: float,
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

    # noinspection PyAttributeOutsideInit
    def resize(self, width: float, bar: int = None, gap: int = None, bar_pct: float = None):
        if not (bar is None) ^ (bar_pct is None) and self._bar is None and self._bar_pct is None:
            raise ValueError('One and only one of bar or bar_pct must be provided')
        if bar is not None:
            self._bar_pct = None
            self.bar = bar
        elif bar_pct is not None:
            self._bar_pct = bar_pct
        self.width = width
        bar = self._bar
        if gap is None:
            gap = ceil(bar / 10)
        if gap < 1:
            raise ValueError(f'Invalid {gap=} size (min: 1px)')
        self.height = 2 * width - bar
        self.gap = gap
        self.seg_height = width - bar

    def calc_width(self, height: float) -> float:
        if self._bar_pct:
            return height / (2 - self._bar_pct)
        elif self._bar:
            return (height + self._bar) / 2

    @property
    def width(self):
        return self._width

    @width.setter
    def width(self, value: float):
        if self._bar_pct:
            self.bar = ceil(value * self._bar_pct)
        if value < (min_width := self._bar * (4 if self._bar % 2 == 0 else 5)):
            raise ValueError(f'Invalid width={value} < {min_width=} based on bar={self.bar}')
        self._width = value  # noqa

    @property
    def bar(self):
        return self._bar

    @bar.setter
    def bar(self, value: int):
        if value < 3:
            raise ValueError(f'Invalid bar={value} size - minimum value is 3 px')
        self._bar = value

    def time_size(self, seconds: bool = True):
        nums, colons = (6, 2) if seconds else (4, 1)
        spaces = nums + colons - 1
        full_width = nums * self._width + colons * self._bar + spaces * self._bar
        return full_width, self.height

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
        for seg in self._bits:
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
        x0 = x_offset
        x1 = x0 + bar
        y0 = y_offset + 2 * bar
        y1 = y0 + bar
        y2 = y1 + 3 * bar
        y3 = y2 + bar
        yield (x0, y0), (x1, y0), (x1, y1), (x0, y1)
        yield (x0, y2), (x1, y2), (x1, y3), (x0, y3)
