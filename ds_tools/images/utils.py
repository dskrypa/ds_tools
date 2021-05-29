"""
Utilities for working with images

:author: Doug Skrypa
"""

import logging
from io import BytesIO
from math import floor, ceil
from pathlib import Path
from typing import Union

from PIL import Image, ImageColor
from PIL.Image import Image as PILImage
from PIL.ImagePalette import ImagePalette

__all__ = [
    'ImageType',
    'Size',
    'Box',
    'as_image',
    'image_to_bytes',
    'calculate_resize',
    'scale_image',
    'color_to_rgb',
    'color_to_alpha',
    'palette_index_to_color',
    'color_at_pos',
]
log = logging.getLogger(__name__)
ImageType = Union[PILImage, bytes, Path, str, None]
Size = tuple[int, int]
Box = tuple[int, int, int, int]


def as_image(image: ImageType) -> PILImage:
    if image is None or isinstance(image, PILImage):
        return image
    elif isinstance(image, bytes):
        return Image.open(BytesIO(image))
    elif isinstance(image, (Path, str)):
        path = Path(image).expanduser()
        if not path.is_file():
            raise ValueError(f'Invalid image path={path.as_posix()!r} - it is not a file')
        return Image.open(path)
    else:
        raise TypeError(f'Image must be bytes, None, Path, str, or a PIL.Image.Image - found {type(image)}')


def image_to_bytes(image: ImageType, format: str = None, size: Size = None, **kwargs) -> bytes:  # noqa
    image = as_image(image)
    if size:
        image = scale_image(image, *size, **kwargs)
    if not (save_fmt := format or image.format):
        save_fmt = 'png' if image.mode == 'RGBA' else 'jpeg'
    if save_fmt == 'jpeg' and image.mode == 'RGBA':
        image = image.convert('RGB')

    bio = BytesIO()
    image.save(bio, save_fmt)
    return bio.getvalue()


def scale_image(image: PILImage, width, height, **kwargs) -> PILImage:
    new_size = calculate_resize(*image.size, width, height)
    return image.resize(new_size, **kwargs)


def calculate_resize(src_w, src_h, new_w, new_h):
    """Copied logic from :meth:`PIL.Image.Image.thumbnail`"""
    x, y = map(floor, (new_w, new_h))
    aspect = src_w / src_h
    if x / y >= aspect:
        x = _round_aspect(y * aspect, key=lambda n: abs(aspect - n / y))
    else:
        y = _round_aspect(x / aspect, key=lambda n: 0 if n == 0 else abs(aspect - x / n))
    return x, y


def _round_aspect(number, key):
    return max(min(floor(number), ceil(number), key=key), 1)


def color_to_rgb(color: str) -> tuple[int, int, int]:
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

    # data = image.getdata()
    # updated = []
    #
    # image.putdata(updated)
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
