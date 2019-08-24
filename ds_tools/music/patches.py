"""
:author: Doug Skrypa
"""

import logging
import string
from numbers import Number
from unicodedata import normalize

from mutagen.id3._frames import Frame
from mutagen.mp4 import AtomDataType, MP4Cover, MP4FreeForm, MP4Tags
from plexapi.audio import Track
from plexapi.base import OPERATORS, PlexObject
from plexapi.playlist import Playlist

__all__ = ['tag_repr', 'apply_mutagen_patches', 'apply_plex_patches']
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


def apply_plex_patches():
    """
    Monkey-patch...
      - PlexObject's _getAttrOperator to avoid an O(n) operation (n=len(OPERATORS)) on every object in searches, and to
        support negation via __not__{op}
      - PlexObject's fetchItem operators to include a compiled regex pattern search
      - PlexObject's _getAttrValue for minor optimizations
      - PlexObject's _checkAttrs to fix op=exact behavior, and to support filtering based on if an attribute is not set
      - Playlist to support semi-bulk item removal (the Plex REST API does not have a bulk removal handler, but the
        removeItems method added below removes the reload step between items)
      - Track to have a more readable/useful repr
      - Track to be sortable
    """
    OPERATORS.update({
        'sregex': lambda v, pat: pat.search(v),
        'nsregex': lambda v, pat: not pat.search(v),
        'is': lambda v, q: v is q,
        'notset': lambda v, q: (not v) if q else v,
        'custom': None
    })
    op_cache = {}

    def _bool(value):
        if isinstance(value, str):
            try:
                return bool(int(value))
            except ValueError:
                pass
        return bool(value)

    def get_attr_operator(attr):
        try:
            base, op = attr.rsplit('__', 1)
        except ValueError:
            return attr, 'exact', OPERATORS['exact']
        else:
            try:
                operator = OPERATORS[op]
            except KeyError:
                return attr, 'exact', OPERATORS['exact']
            else:
                if base.endswith('__not'):
                    return base[:-5], 'not ' + op, lambda *a: not operator(*a)
                return base, op, operator

    def _get_attr_operator(self, attr):
        try:
            return op_cache[attr]
        except KeyError:
            base, op, operator = get_attr_operator(attr)
            log.debug('get_attr_operator({!r}) => attr={!r}, op={!r}, operator={}'.format(attr, base, op, operator))
            op_cache[attr] = (base, op, operator)
            return base, op, operator

    def cast_func(op, query):
        if op not in ('exists', 'notset'):
            if isinstance(query, bool):
                return lambda x: _bool(x)
            elif isinstance(query, int):
                return lambda x: float(x) if '.' in x else int(x)
            elif isinstance(query, Number):
                return type(query)
        return lambda x: x

    def get_attr_value(elem, attrstr, results=None):
        # log.debug('Fetching %s in %s', attrstr, elem.tag)
        try:
            attr, attrstr = attrstr.split('__', 1)
        except ValueError:
            lc_attr = attrstr.lower()
            # check were looking for the tag
            if lc_attr == 'etag':
                return [elem.tag]
            # loop through attrs so we can perform case-insensitive match
            for _attr, value in elem.attrib.items():
                if lc_attr == _attr.lower():
                    return [value]
            return []
        else:
            lc_attr = attr.lower()
            results = [] if results is None else results
            for child in (c for c in elem if c.tag.lower() == lc_attr):
                results += get_attr_value(child, attrstr, results)
            return [r for r in results if r is not None]

    def _checkAttrs(self, elem, **kwargs):
        for attr, query in kwargs.items():
            attr, op, operator = _get_attr_operator(None, attr)
            if op == 'custom':
                if not query(elem.attrib):
                    return False
            else:
                values = get_attr_value(elem, attr)
                # special case query in (None, 0, '') to include missing attr
                if op == 'exact' and not values and query in (None, 0, ''):
                    # original would return True here, bypassing other filters, which was bad!
                    pass
                elif op == 'notset':
                    if not operator(values, query):
                        return False
                else:
                    cast = cast_func(op, query)
                    # return if attr were looking for is missing
                    for value in values:
                        try:
                            value = cast(value)
                        except ValueError:
                            log.error('Unable to cast attr={} value={} from elem={}'.format(attr, value, elem))
                            raise
                        else:
                            if operator(value, query):
                                break
                    else:
                        return False
        return True

    def removeItems(self, items):
        """ Remove multiple tracks from a playlist. """
        del_method = self._server._session.delete
        uri_fmt = '{}/items/{{}}'.format(self.key)
        results = [self._server.query(uri_fmt.format(item.playlistItemID), method=del_method) for item in items]
        self.reload()
        return results

    def stars(rating, out_of=10, num_stars=5, chars=('\u2605', '\u2730')):
        if out_of < 1:
            raise ValueError('out_of must be > 0')
        filled = int(num_stars * rating / out_of)
        empty = num_stars - filled
        a, b = chars
        return a * filled + b * empty

    def track_repr(self):
        key = self.key.replace('/library/metadata/', '')
        fmt = '<{}#{}[{}]({!r}, artist={!r}, album={!r})>'
        rating = stars(self.userRating)
        return fmt.format(type(self).__name__, key, rating, self.title, self.grandparentTitle, self.parentTitle)

    def track_lt(self, other):
        return int(self.key.replace('/library/metadata/', '')) < int(other.key.replace('/library/metadata/', ''))

    PlexObject._getAttrOperator = _get_attr_operator
    PlexObject._checkAttrs = _checkAttrs
    Playlist.removeItems = removeItems
    Track.__repr__ = track_repr
    Track.__lt__ = track_lt
