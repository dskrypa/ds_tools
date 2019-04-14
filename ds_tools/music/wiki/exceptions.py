"""
:author: Doug Skrypa
"""

import re
from urllib.parse import urlparse

from ...core import cached_property
from ...utils import soupify
from ..exceptions import MusicException

__all__ = [
    'AmbiguousEntityException', 'InvalidTrackListException', 'MemberDiscoveryException', 'MusicWikiException',
    'WikiEntityIdentificationException', 'WikiEntityInitException', 'WikiTypeError'
]


class MusicWikiException(MusicException):
    """Base Exception class for the music.wiki package"""


class WikiEntityInitException(MusicWikiException):
    """Exception to be raised when unable to initialize a WikiEntity"""


class WikiEntityIdentificationException(WikiEntityInitException):
    """Exception to be raised when unable to identify a WikiEntity definitively"""


class InvalidTrackListException(MusicWikiException):
    """Exception to be raised when an invalid track list name was provided"""


class MemberDiscoveryException(MusicWikiException):
    """Exception to be raised when unable to find a member/sub-unit of a given group"""


class WikiTypeError(TypeError, MusicWikiException):
    """Exception to be raised when an incorrect type was used to initialize a WikiEntity"""
    def __init__(self, url_or_msg, article=None, category=None, cls_cat=None, cls=None):
        self.url, self.article, self.category, self.cls_cat, self.cls = url_or_msg, article, category, cls_cat, cls
        self.msg = None if article else url_or_msg

    def __str__(self):
        if self.msg:
            return self.msg
        fmt = 'Invalid URL for {}: {} - it is {} {} page; expected: {}'
        return fmt.format(self.cls.__name__, self.url, self.article, self.category, self.cls_cat)


class AmbiguousEntityException(MusicWikiException):
    def __init__(self, uri_path, html, obj_type=None):
        parsed_url = urlparse(uri_path)
        self.site = parsed_url.hostname
        self.uri_path = parsed_url.path
        self.html = html
        self.obj_type = obj_type or 'Page'

    @cached_property
    def alternative(self):
        alts = self.alternatives
        return alts[0] if len(alts) == 1 else None

    @staticmethod
    def _alt_text(anchor):
        href = anchor.get('href') or ''
        href = href[6:] if href.startswith('/wiki/') else href
        return href if href else anchor.text.strip()

    @cached_property
    def alternatives(self):
        soup = soupify(self.html)
        try:
            a = soup.find('span', class_='alternative-suggestion').find('a')
        except Exception as e:
            pass
        else:
            if a:
                return [self._alt_text(a)]

        disambig_div = soup.find('div', id='disambig')
        if disambig_div:
            return [self._alt_text(a) for li in disambig_div.parent.find('ul') for a in li.find_all('a', limit=1)]

        #if re.search(r'For other uses, see.*?\(disambiguation\)', self.html, re.IGNORECASE):
        disambig_a = soup.find('a', class_='mw-disambig')
        if disambig_a:
            return [self._alt_text(disambig_a)]

        if not re.search(r'For other uses, see.*?\(disambiguation\)', self.html, re.IGNORECASE):
            try:
                ul = soup.find('div', class_='mw-parser-output').find('ul')
            except Exception:
                pass
            else:
                return [self._alt_text(a) for li in ul.find_all('li') for a in li.find_all('a', limit=1)]
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
