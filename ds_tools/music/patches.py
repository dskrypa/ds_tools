"""
:author: Doug Skrypa
"""

import logging
import string
from unicodedata import normalize

from mutagen.id3._frames import Frame
from mutagen.mp4 import AtomDataType, MP4Cover, MP4FreeForm, MP4Tags

__all__ = ['tag_repr', 'apply_mutagen_patches']
log = logging.getLogger(__name__)

# Translate whitespace characters (such as \n, \r, etc.) to their escape sequences
WHITESPACE_TRANS_TBL = str.maketrans({c: c.encode('unicode_escape').decode('utf-8') for c in string.whitespace})


def tag_repr(tag_val, max_len=125, sub_len=25):
    tag_val = normalize('NFC', str(tag_val)).translate(WHITESPACE_TRANS_TBL)
    if len(tag_val) > max_len:
        return '{}...{}'.format(tag_val[:sub_len], tag_val[-sub_len:])
    return tag_val


def apply_mutagen_patches():
    """
    Monkey-patch...
      - Frame's repr so APIC and similar frames don't kill terminals
      - MP4Tags to add an unofficial POPM integer field to MP4Tags to store song ratings
    """
    # noinspection PyUnresolvedReferences
    MP4Tags._MP4Tags__atoms[b'POPM'] = (MP4Tags._MP4Tags__parse_integer, MP4Tags._MP4Tags__render_integer, 1)

    _orig_frame_repr = Frame.__repr__
    def _frame_repr(self):
        kw = []
        for attr in self._framespec:
            # so repr works during __init__
            if hasattr(self, attr.name):
                kw.append('{}={}'.format(attr.name, tag_repr(repr(getattr(self, attr.name)))))
        for attr in self._optionalspec:
            if hasattr(self, attr.name):
                kw.append('{}={}'.format(attr.name, tag_repr(repr(getattr(self, attr.name)))))
        return '{}({})'.format(type(self).__name__, ', '.join(kw))
    Frame.__repr__ = _frame_repr

    _orig_reprs = {}

    def _MP4Cover_repr(self):
        return '{}({}, {})'.format(type(self).__name__, tag_repr(bytes(self), 10, 5), AtomDataType(self.imageformat))

    def _MP4FreeForm_repr(self):
        return '{}({}, {})'.format(type(self).__name__, tag_repr(bytes(self), 10, 5), AtomDataType(self.dataformat))

    for cls in (MP4Cover, MP4FreeForm):
        _orig_reprs[cls] = cls.__repr__

    MP4Cover.__repr__ = _MP4Cover_repr
    MP4FreeForm.__repr__ = _MP4FreeForm_repr
