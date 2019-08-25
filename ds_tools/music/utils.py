"""
:author: Doug Skrypa
"""

import logging

__all__ = ['stars']
log = logging.getLogger(__name__)


def stars(rating, out_of=10, num_stars=5, chars=('\u2605', '\u2730'), half='\u00BD'):
    if out_of < 1:
        raise ValueError('out_of must be > 0')

    filled, remainder = map(int, divmod(num_stars * rating, out_of))
    if half and remainder:
        empty = num_stars - filled - 1
        mid = half
    else:
        empty = num_stars - filled
        mid = ''
    a, b = chars
    return (a * filled) + mid + (b * empty)
