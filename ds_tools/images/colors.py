"""
Utilities for working with colors in images

:author: Doug Skrypa
"""

from random import randrange
from typing import Union, Collection

from PIL import ImageColor
from PIL.Image import Image as PILImage
from PIL.ImagePalette import ImagePalette

from .utils import ImageType, as_image

__all__ = ['color_to_rgb', 'color_to_alpha', 'palette_index_to_color', 'color_at_pos', 'find_unused_color']
RGB = tuple[int, int, int]


def color_to_rgb(color: str) -> RGB:
    try:
        return ImageColor.getrgb(color)
    except ValueError:
        if isinstance(color, str) and len(color) in (3, 4, 6, 8):
            return ImageColor.getrgb(f'#{color}')
        raise


def color_to_alpha(image: ImageType, color: str) -> PILImage:
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
