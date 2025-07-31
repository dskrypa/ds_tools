"""
Utilities for working with images

:author: Doug Skrypa
"""

from __future__ import annotations

import json
from copy import deepcopy
from io import BytesIO, StringIO
from math import floor, ceil
from pathlib import Path
from typing import TYPE_CHECKING, Any

from PIL.Image import Image as PILImage, open as open_image, MIME
from PIL.JpegImagePlugin import RAWMODE

from ..core.serialization import PermissiveJSONEncoder

if TYPE_CHECKING:
    from .typing import ImageType, Size

__all__ = ['as_image', 'image_to_bytes', 'calculate_resize', 'scale_image', 'get_image_path', 'get_image_info']


def as_image(image: ImageType) -> PILImage:
    match image:  # noqa  # PyCharm bug
        case str() | Path():
            path = Path(image).expanduser()
            if not path.is_file():
                raise ValueError(f'Invalid image path={path.as_posix()!r} - it is not a file')
            return open_image(path)
        case None | PILImage():
            return image
        case bytes():
            return open_image(BytesIO(image))
        case _:
            raise TypeError(f'Image must be bytes, None, Path, str, or a PIL.Image.Image - found {type(image)}')


def image_to_bytes(image: ImageType, format: str = None, size: Size = None, **kwargs) -> bytes:  # noqa
    image = as_image(image)
    if size:
        image = scale_image(image, *size, **kwargs)

    save_fmt = format or image.format
    if not save_fmt:
        save_fmt = 'png' if image.mode == 'RGBA' else 'jpeg'

    if save_fmt == 'jpeg' and image.mode not in RAWMODE:
        image = image.convert('RGB')

    bio = BytesIO()
    image.save(bio, save_fmt)
    return bio.getvalue()


def scale_image(image: PILImage, width, height, **kwargs) -> PILImage:
    new_size = calculate_resize(*image.size, width, height)
    return image.resize(new_size, **kwargs)


def calculate_resize(src_w, src_h, new_w, new_h):
    """Copied logic from :meth:`PIL.Image.Image.thumbnail`"""
    x, y = floor(new_w), floor(new_h)
    aspect = src_w / src_h
    if x / y >= aspect:
        x = _round_aspect(y * aspect, key=lambda n: abs(aspect - n / y))
    else:
        y = _round_aspect(x / aspect, key=lambda n: 0 if n == 0 else abs(aspect - x / n))
    return x, y


def _round_aspect(number, key):
    rounded = min(floor(number), ceil(number), key=key)
    return rounded if rounded > 1 else 1


def get_image_path(image: ImageType) -> Path | None:
    match image:
        case Path():
            return image.expanduser()
        case str():
            return Path(image).expanduser()
        case PILImage():
            return _get_image_path(image)
        case _:
            return None


def _get_image_path(image: PILImage) -> Path | None:
    try:
        return Path(image.filename)  # noqa
    except (AttributeError, TypeError):
        pass
    try:
        return Path(image.fp.name)
    except (AttributeError, TypeError):
        return None


def get_image_info(image: ImageType, as_str: bool = False, identifier: str = None) -> dict[str, Any] | str:
    image = as_image(image)
    info = deepcopy(image.info)
    info['mode'] = image.mode
    info['size'] = '{}x{}'.format(*image.size)
    info['class'] = image.__class__.__qualname__
    if fmt := image.format:
        info['format'] = image.format
        info['mime_type'] = MIME[fmt]
        if fmt == 'GIF':
            attrs = ('disposal_method', 'disposal', 'dispose_extent', 'tile')
            info.update((attr, getattr(image, attr, None)) for attr in attrs)
    if palette := image.palette:
        info['palette'] = f'<ImagePalette[mode={palette.mode!r}, raw={palette.rawmode}, len={len(palette.palette)}]>'

    if not as_str:
        return info

    if identifier is None:
        if path := _get_image_path(image):
            identifier = path.as_posix()
        else:
            identifier = str(image)

    sio = StringIO()
    sio.write(f'---\n{identifier}:')
    for key, val in sorted(info.items()):
        if not isinstance(val, (str, int, float)):
            val = json.dumps(val, cls=PermissiveJSONEncoder)
        sio.write(f'\n  {key}: {val}')
    return sio.getvalue()
