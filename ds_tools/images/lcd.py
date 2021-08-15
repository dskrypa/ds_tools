"""
LCD Clock numbers

:author: Doug Skrypa
"""

import logging
from datetime import datetime
from typing import Union

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
