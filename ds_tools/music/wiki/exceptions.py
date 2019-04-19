"""
:author: Doug Skrypa
"""

import logging
import re
from urllib.parse import urlparse

from ...core import cached_property
from ...utils import soupify
from ..exceptions import MusicException

__all__ = [
    'AmbiguousEntityException', 'InvalidTrackListException', 'MemberDiscoveryException', 'MusicWikiException',
    'WikiEntityIdentificationException', 'WikiEntityInitException', 'WikiTypeError'
]
log = logging.getLogger(__name__)


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
        self._alt_texts = None

    @cached_property
    def alternative(self):
        alts = self.alternatives
        return alts[0] if len(alts) == 1 else None

    def _alt_text(self, anchor):
        href = anchor.get('href') or ''
        href = href[6:] if href.startswith('/wiki/') else href
        if self._alt_texts is None:
            self._alt_texts = [anchor.text.strip()]
        else:
            self._alt_texts.append(anchor.text.strip())
        return None if '&redlink=1' in href else href

    @cached_property
    def alternative_texts(self):
        if self._alt_texts is None:
            # noinspection PyStatementEffect
            self.alternatives
        return []

    @cached_property
    def alternatives(self):
        soup = soupify(self.html)
        try:
            a = soup.find('span', class_='alternative-suggestion').find('a')
        except Exception as e:
            pass
        else:
            if a:
                return list(filter(None, self._alt_text(a)))

        disambig_div = soup.find('div', id='disambig')
        if disambig_div:
            anchors = (self._alt_text(a) for li in disambig_div.parent.find('ul') for a in li.find_all('a', limit=1))
            return list(filter(None, anchors))

        #if re.search(r'For other uses, see.*?\(disambiguation\)', self.html, re.IGNORECASE):
        disambig_a = soup.find('a', class_='mw-disambig')
        if disambig_a:
            return list(filter(None, self._alt_text(disambig_a)))

        r'redirects here.\s+For the .*?, see'

        pats = (r'For other uses, see.*?\(disambiguation\)', r'redirects here.\s+For the .*?, see')
        if not any(re.search(pat, self.html, re.IGNORECASE) for pat in pats):
            try:
                ul = soup.find('div', class_='mw-parser-output').find('ul')
            except Exception:
                pass
            else:
                anchors = (self._alt_text(a) for li in ul.find_all('li') for a in li.find_all('a', limit=1))
                return list(filter(None, anchors))

        if re.search(r'redirects here.\s+For the pop music group, see', self.html, re.IGNORECASE):
            for div in soup.find_all('div', class_='hatnote'):
                if 'For the pop music group' in div.text:
                    anchors = (self._alt_text(a) for a in div.find_all('a', limit=1))
                    return list(filter(None, anchors))
        return []

    def __str__(self):
        alts = self.alternative_texts
        base = '{} {!r} doesn\'t exist'.format(self.obj_type, self.uri_path)
        if len(alts) == 1:
            return '{} - did you mean {!r}?'.format(base, alts[0])
        elif alts:
            return '{} - did you mean one of these? {}'.format(base, ' | '.join(alts))
        else:
            return '{} and no suggestions could be found.'.format(base)
