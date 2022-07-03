"""
Utilities for working with colors in images

:author: Doug Skrypa
"""

from random import randrange
from typing import Union, Collection

import numpy
from PIL.Image import Image as PILImage, fromarray as image_from_array
from PIL.ImageColor import getrgb
from PIL.ImagePalette import ImagePalette

from .utils import ImageType, as_image

__all__ = [
    'color_to_rgb',
    'color_to_alpha',
    'palette_index_to_color',
    'color_at_pos',
    'find_unused_color',
    'RGB',
    'RGBA',
    'Color',
    'replace_color',
]

RGB = tuple[int, int, int]
RGBA = tuple[int, int, int, int]
Color = Union[str, RGB, RGBA]


def color_to_rgb(color: Color) -> Union[RGB, RGBA]:
    if isinstance(color, tuple):
        return color
    try:
        return getrgb(color)
    except ValueError:
        if isinstance(color, str) and len(color) in (3, 4, 6, 8):
            return getrgb(f'#{color}')
        raise


def color_to_alpha(image: ImageType, color: Color) -> PILImage:
    r, g, b = color_to_rgb(color)
    image = as_image(image).convert('RGBA')
    data = image.load()
    width, height = image.size
    for x in range(width):
        for y in range(height):
            pr, pg, pb, pa = data[x, y]
            a = max(abs(pr - r), abs(pg - g), abs(pb - b))
            data[x, y] = pr, pg, pb, a
    return image


def palette_index_to_color(image_or_palette: Union[ImageType, ImagePalette], index: int) -> tuple[int, ...]:
    if isinstance(image_or_palette, ImagePalette):
        palette = image_or_palette
    else:
        image = as_image(image_or_palette)
        if not (palette := image.palette):
            raise ValueError(f'Image={image} has no palette')
    chars = len(palette.mode)
    offset = chars * index
    return tuple(palette.palette[offset:offset + chars])


def color_at_pos(image: ImageType, pos: tuple[int, int]) -> Union[tuple[int, ...], int]:
    image = as_image(image)
    color = image.getpixel(pos)
    if isinstance(color, tuple):
        return color
    elif image.palette:
        return palette_index_to_color(image.palette, color)
    else:
        return color


def find_unused_color(used: Collection[RGB]) -> RGB:
    used = set(used)
    if len(used) > 256 ** 3:
        raise ValueError(f'Too many colors ({len(used)}) - impossible to generate different unique random color')
    while True:
        color = (randrange(256), randrange(256), randrange(256))
        if color not in used:
            return color


def replace_color(image: ImageType, old_color: Color, new_color: Color) -> PILImage:
    old_r, old_g, old_b = color_to_rgb(old_color)[:3]
    new_color = color_to_rgb(new_color)[:3]
    image = as_image(image)
    if (orig_mode := image.mode) != 'RGBA':
        image = image.convert('RGBA')
    data = numpy.array(image)  # noqa
    r, g, b, a = data.T
    to_replace = (r == old_r) & (g == old_g) & (b == old_b)
    data[..., :-1][to_replace.T] = new_color  # noqa
    updated = image_from_array(data)
    if orig_mode != 'RGBA':
        updated = updated.convert(orig_mode)
    return updated
