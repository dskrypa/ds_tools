"""
Utilities for working with images

:author: Doug Skrypa
"""

import json
import logging
from copy import deepcopy
from io import BytesIO, StringIO
from math import floor, ceil
from pathlib import Path
from typing import Union, Any

from PIL import Image
from PIL.Image import Image as PILImage

from ..core.serialization import PermissiveJSONEncoder

__all__ = [
    'ImageType',
    'Size',
    'Box',
    'FloatBox',
    'as_image',
    'image_to_bytes',
    'calculate_resize',
    'scale_image',
    'get_image_info',
]
log = logging.getLogger(__name__)
ImageType = Union[PILImage, bytes, Path, str, None]
Size = tuple[int, int]
Box = tuple[int, int, int, int]
FloatBox = tuple[float, float, float, float]


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


def get_image_info(image: ImageType, as_str: bool = False, identifier: str = None) -> Union[dict[str, Any], str]:
    image = as_image(image)
    info = deepcopy(image.info)
    info['mode'] = image.mode
    info['size'] = '{}x{}'.format(*image.size)
    info['class'] = image.__class__.__qualname__
    if fmt := image.format:
        info['format'] = image.format
        info['mime_type'] = Image.MIME[fmt]
        if fmt == 'GIF':
            attrs = ('disposal_method', 'disposal', 'dispose_extent', 'tile')
            info.update((attr, getattr(image, attr, None)) for attr in attrs)
    if palette := image.palette:
        info['palette'] = f'<ImagePalette[mode={palette.mode!r}, raw={palette.rawmode}, len={len(palette.palette)}]>'

    if as_str:
        if identifier is None:
            try:
                identifier = Path(image.filename).as_posix()
            except Exception:
                try:
                    identifier = Path(image.fp.name).as_posix()
                except Exception:
                    identifier = str(image)

        sio = StringIO()
        sio.write(f'---\n{identifier}:')
        for key, val in sorted(info.items()):
            if not isinstance(val, (str, int, float)):
                val = json.dumps(val, cls=PermissiveJSONEncoder)
            sio.write(f'\n  {key}: {val}')
        return sio.getvalue()
    else:
        return info
