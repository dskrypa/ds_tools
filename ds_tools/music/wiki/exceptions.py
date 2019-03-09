"""
:author: Doug Skrypa
"""

from collections import OrderedDict

from ...core import cached_property
from ...utils import soupify
from ..exceptions import MusicException

__all__ = [
    'AmbiguousEntityException', 'InvalidTrackListException', 'MusicWikiException', 'WikiEntityIdentificationException',
    'WikiEntityInitException', 'WikiTypeError'
]


class MusicWikiException(MusicException):
    """Base Exception class for the music.wiki package"""


class WikiEntityInitException(MusicWikiException):
    """Exception to be raised when unable to initialize a WikiEntity"""


class WikiEntityIdentificationException(WikiEntityInitException):
    """Exception to be raised when unable to identify a WikiEntity definitively"""


class InvalidTrackListException(MusicWikiException):
    """Exception to be raised when an invalid track list name was provided"""


class WikiTypeError(TypeError, MusicWikiException):
    """Exception to be raised when an incorrect type was used to initialize a WikiEntity"""
    def __init__(self, url, article, category, cls_cat):
        self.url, self.article, self.category, self.cls_cat = url, article, category, cls_cat

    def __str__(self):
        return '{} is {} {} page (expected: {})'.format(self.url, self.article, self.category, self.cls_cat)


class AmbiguousEntityException(MusicWikiException):
    def __init__(self, uri_path, html, obj_type=None):
        self.uri_path = uri_path
        self.html = html
        self.obj_type = obj_type or 'Page'

    @cached_property
    def alternative(self):
        alts = self.alternatives
        return alts[0] if len(alts) == 1 else None

    @property
    def potential_alternatives(self):
        alts = []
        for func in ('title', 'upper'):
            val = getattr(self.uri_path, func)()
            if val != self.uri_path:
                alts.append(val)
        return alts

    @cached_property
    def alternatives(self):
        soup = soupify(self.html)
        try:
            a = soup.find('span', class_='alternative-suggestion').find('a')
            return [a.get('href')[6:] if a.get('href') else a.text.strip()]
        except Exception as e:
            pass

        disambig_div = soup.find('div', id='disambig')
        if disambig_div:
            return [
                a.get('href')[6:] if a.get('href') else a.text.strip()
                for li in disambig_div.parent.find('ul')
                for a in li.find_all('a', limit=1)
            ]
        return []

    def __str__(self):
        alts = self.alternatives
        base = '{} {!r} doesn\'t exist'.format(self.obj_type, self.uri_path)
        if len(alts) == 1:
            return '{} - did you mean {!r}?'.format(base, alts[0])
        elif alts:
            return '{} - did you mean one of these? {}'.format(base, ' | '.join(alts))
        else:
            return '{} and no suggestions could be found.'.format(base)
