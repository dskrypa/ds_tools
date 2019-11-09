"""
:author: Doug Skrypa
"""

import atexit
import logging
import string
from numbers import Number
from typing import Iterable, Hashable
from unicodedata import normalize

from mutagen.id3._frames import Frame
from mutagen.mp4 import AtomDataType, MP4Cover, MP4FreeForm, MP4Tags
from plexapi.audio import Track, Album, Artist
from plexapi.base import OPERATORS, PlexObject
from plexapi.playlist import Playlist

from .utils import stars

__all__ = ['tag_repr', 'apply_mutagen_patches', 'apply_plex_patches', 'track_repr']
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


def cls_name(obj):
    return type(obj).__name__


def track_repr(self, rating=None):
    fmt = '<{}#{}[{}]({!r}, artist={!r}, album={!r})>'
    rating = stars(rating or self.userRating)
    artist = self.originalTitle if self.grandparentTitle == 'Various Artists' else self.grandparentTitle
    return fmt.format(cls_name(self), self._int_key(), rating, self.title, artist, self.parentTitle)


def apply_plex_patches(deinit_colorama=True):
    """
    Monkey-patch...
      - PlexObject's _getAttrOperator to avoid an O(n) operation (n=len(OPERATORS)) on every object in searches, and to
        support negation via __not__{op}
      - PlexObject's fetchItem operators to include a compiled regex pattern search
      - PlexObject's _getAttrValue for minor optimizations
      - PlexObject's _checkAttrs to fix op=exact behavior, and to support filtering based on if an attribute is not set
      - Playlist to support semi-bulk item removal (the Plex REST API does not have a bulk removal handler, but the
        removeItems method added below removes the reload step between items)
      - Track, Album, and Artist to have more readable/useful reprs
      - PlexObject to be sortable

    :param bool deinit_colorama: plexapi.utils imports tqdm (it uses it to print a progress bar during downloads); when
      importing tqdm, tqdm imports and initializes colorama.  Colorama ends up raising exceptions when piping output to
      ``| head``.  Defaults to True.
    """
    OPERATORS.update({
        'custom': None,
        'lc': lambda v, q: v.lower() == q.lower(),
        'eq': lambda v, q: v == q,
        'ieq': lambda v, q: v.lower() == q.lower(),
        'sregex': lambda v, pat: pat.search(v),
        # 'nsregex': lambda v, pat: print('{} !~ {!r}: {}'.format(pat, v, not pat.search(v))) or not pat.search(v),
        'nsregex': lambda v, pat: not pat.search(v),
        'is': lambda v, q: v is q,
        'notset': lambda v, q: (not v) if q else v,
        'is_odd': lambda v, q: divmod(int(float(v)), 2)[1],
        'is_even': lambda v, q: not divmod(int(float(v)), 2)[1],
        'not_in': lambda v, q: v not in q
    })
    op_cache = {}

    if deinit_colorama:
        try:
            import colorama
        except ImportError:
            pass
        else:
            colorama.deinit()
            atexit.unregister(colorama.initialise.reset_all)

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

    cast_funcs = {}

    def cast_func(op, query):
        key = (op, tuple(query) if not isinstance(query, Hashable) else query)
        try:
            return cast_funcs[key]
        except KeyError:
            if op in ('is_odd', 'is_even'):
                func = int
            elif op not in ('exists', 'notset'):
                if isinstance(query, bool):
                    func = lambda x: _bool(x)
                elif isinstance(query, int):
                    func = lambda x: float(x) if '.' in x else int(x)
                elif isinstance(query, Number):
                    func = type(query)
                elif op == 'in' and isinstance(query, Iterable) and not isinstance(query, str):
                    types = {type(v) for v in query}
                    if len(types) == 1:
                        func = next(iter(types))
                    elif all(isinstance(v, Number) for v in query):
                        func = float
                    else:
                        log.debug('No common type found for values in {}'.format(query))
                        func = lambda x: x
                else:
                    func = lambda x: x
            else:
                func = lambda x: x

            if func is int:
                func = lambda x: float(x) if '.' in x else int(x)

            cast_funcs[key] = func
            return func

    def get_attr_value(elem, attrstr, results=None):
        # log.debug('Fetching {} in {}'.format(attrstr, elem.tag))
        try:
            attr, attrstr = attrstr.split('__', 1)
        except ValueError:
            lc_attr = attrstr.lower()
            # check were looking for the tag
            if lc_attr == 'etag':
                # if elem.tag == 'Genre':
                #     log.debug('Returning [{}]'.format(elem.tag))
                return [elem.tag]
            # loop through attrs so we can perform case-insensitive match
            for _attr, value in elem.attrib.items():
                if lc_attr == _attr.lower():
                    # if elem.tag == 'Genre':
                    #     log.debug('Returning {}'.format(value))
                    return [value]
            # if elem.tag == 'Genre':
            #     log.debug('Returning []')
            return []
        else:
            lc_attr = attr.lower()
            results = [] if results is None else results
            for child in (c for c in elem if c.tag.lower() == lc_attr):
                results += get_attr_value(child, attrstr, results)
            # if elem.tag == 'Genre':
            #     log.debug('Returning {}'.format([r for r in results if r is not None]))
            return [r for r in results if r is not None]

    def _cast(cast, value, attr, elem):
        try:
            return cast(value)
        except ValueError:
            log.error('Unable to cast attr={} value={} from elem={}'.format(attr, value, elem))
            raise

    def _checkAttrs(self, elem, **kwargs):
        for attr, query in kwargs.items():
            attr, op, operator = _get_attr_operator(None, attr)
            # if op == 'nsregex':
            #     log.debug('Processing {!r} with op={}'.format(elem.attrib.get('title'), op))
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
                    if op in ('ne', 'nsregex') or 'not' in op:
                        # If any value is not truthy for a negative filter, then it should be filtered out
                        if not all(operator(_cast(cast, value, attr, elem), query) for value in values):
                            return False
                    else:
                        for value in values:
                            if operator(_cast(cast, value, attr, elem), query):
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

    def album_repr(self):
        fmt = '<{}#{}[{}]({!r}, artist={!r}, genres={})>'
        rating = stars(float(self._data.attrib.get('userRating', 0)))
        genres = ', '.join(g.tag for g in self.genres)
        return fmt.format(cls_name(self), self._int_key(), rating, self.title, self.parentTitle, genres)

    def artist_repr(self):
        fmt = '<{}#{}[{}]({!r}, genres={})>'
        rating = stars(float(self._data.attrib.get('userRating', 0)))
        genres = ', '.join(g.tag for g in self.genres)
        return fmt.format(cls_name(self), self._int_key(), rating, self.title, genres)

    def full_info(ele):
        return {'_type': ele.tag, 'attributes': ele.attrib, 'elements': [full_info(e) for e in ele]}

    PlexObject._getAttrOperator = _get_attr_operator
    PlexObject._checkAttrs = _checkAttrs
    PlexObject._int_key = lambda self: int(self._clean(self.key))
    PlexObject.__lt__ = lambda self, other: int(self._clean(self.key)) < int(other._clean(other.key))
    PlexObject.as_dict = lambda self: full_info(self._data)

    Playlist.removeItems = removeItems
    Track.__repr__ = track_repr
    Album.__repr__ = album_repr
    Artist.__repr__ = artist_repr
