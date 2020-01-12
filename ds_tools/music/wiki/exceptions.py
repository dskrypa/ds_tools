"""
:author: Doug Skrypa
"""

import logging
import re
from urllib.parse import urlparse, unquote

import bs4

from ...compat import cached_property
from ...utils import soupify
from ..exceptions import MusicException

__all__ = [
    'AmbiguousEntityException', 'InvalidTrackListException', 'MemberDiscoveryException', 'MusicWikiException',
    'WikiEntityIdentificationException', 'WikiEntityInitException', 'WikiTypeError', 'WikiAlbumPartProcessingError',
    'NoPrimaryArtistError', 'NoUrlFoundException', 'InvalidWikiClientException'
]
log = logging.getLogger(__name__)
logr = {'ambig_parsing': logging.getLogger(__name__ + '.ambig_parsing')}
for logger in logr.values():
    logger.setLevel(logging.WARNING)


class MusicWikiException(MusicException):
    """Base Exception class for the music.wiki package"""


class WikiEntityInitException(MusicWikiException):
    """Exception to be raised when unable to initialize a WikiEntity"""


class InvalidWikiClientException(WikiEntityInitException):
    """Exception to be raised when an invalid Wiki client host is provided"""


class NoUrlFoundException(WikiEntityInitException):
    """Exception to be raised when no URL can be found when trying to initialize a WikiEntity"""


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
    def __init__(self, url, html, obj_type=None):
        self.url = url
        parsed_url = urlparse(url)
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
        if href and '&redlink=1' not in href:
            # log.debug('Storing anchor text={!r} for href={!r}'.format(anchor.text.strip(), unquote(href)))
            if self._alt_texts is None:
                self._alt_texts = [anchor.text.strip()]
            else:
                self._alt_texts.append(anchor.text.strip())
            return unquote(href)
        return None

    @cached_property
    def alternative_texts(self):
        if self._alt_texts is None:
            # noinspection PyStatementEffect
            self.alternatives
        return self._alt_texts or []

    @property
    def _soup(self):
        # soupify every time so that elements may be modified/removed without affecting other functions
        return soupify(self.html, parse_only=bs4.SoupStrainer('div', id='mw-content-text')) if self.html else None

    @cached_property
    def _clean_soup(self):
        """The soupified page content, with the undesirable parts at the beginning removed"""
        try:
            content = self._soup.find('div', id='mw-content-text')
        except AttributeError as e:
            if self._soup is not None:
                log.warning(e)
            return None

        for rm_ele in content.select('[style~="display:none"]'):
            rm_ele.extract()

        bad_classes = (
            'tocright', 'mw-editsection', 'reference', 'hatnote', 'infobox', 'noprint', 'dablink', 'mw-empty-elt',
            'shortdescription', 'box-Multiple_issues', 'box-Unreliable_sources', 'box-BLP_sources',
            'box-More_citations_needed'
        )
        for clz in bad_classes:
            for rm_ele in content.find_all(class_=clz):
                rm_ele.extract()

        return content

    @cached_property
    def alternatives(self):
        _log = logr['ambig_parsing']
        soup = self._clean_soup
        try:
            a = soup.find('span', class_='alternative-suggestion').find('a')
        except Exception as e:
            _log.debug('Error finding alt suggestion in {}: {}'.format(self.url, e))
        else:
            if a:
                _log.debug('Found alt suggestion anchor in {}: {}'.format(self.url, a))
                return list(filter(None, (self._alt_text(a),)))
            # else:
            #     _log.debug('Did not find an alt suggestion anchor in {}'.format(self.url))

        disambig_div = soup.find('div', id='disambig')
        if disambig_div:
            anchors = (self._alt_text(a) for li in disambig_div.parent.find('ul') for a in li.find_all('a', limit=1))
            alts = list(filter(None, anchors))
            _log.debug('Found div with id=disambig - links: {}'.format(alts))
            return alts

        #if re.search(r'For other uses, see.*?\(disambiguation\)', self.html, re.IGNORECASE):
        disambig_a = soup.find('a', class_='mw-disambig')
        if disambig_a:
            _log.debug('Found anchor with class=mw-disambig - links: {}'.format(disambig_a))
            return list(filter(None, (self._alt_text(disambig_a),)))

        music_h2_span = soup.find('span', id='Music')
        if music_h2_span:
            try:
                ul = music_h2_span.parent.find_next('ul')
            except Exception as e:
                pass
            else:
                anchors = (
                    self._alt_text(a) for li in ul.find_all('li') for a in li.find_all('a', limit=1)
                    if any(val in li.text.lower() for val in ('korea', 'group', 'artist', 'band', 'singer'))
                )
                _log.debug('Found span with id=Music - links: {}'.format(anchors))
                return list(filter(None, anchors))

        pats = (r'For other uses, see.*?\(disambiguation\)', r'redirects here.\s+For the .*?, see')
        if not any(re.search(pat, self.html, re.IGNORECASE) for pat in pats):
            try:
                body = soup.find('div', class_='mw-parser-output')
            except Exception:
                pass
            else:
                if body:
                    anchors = (
                        self._alt_text(a)
                        for ul in body.find_all('ul')
                        for li in ul.find_all('li')
                        for a in li.find_all('a', limit=1)
                        if any(val in li.text.lower() for val in ('korea', 'group', 'artist', 'band', 'singer'))
                    )
                    _log.debug('Found ul in div with class=mw-parser-output - links: {}'.format(anchors))
                    return list(filter(None, anchors))

        if re.search(r'redirects here.\s+For the pop music group, see', self.html, re.IGNORECASE):
            for div in soup.find_all('div', class_='hatnote'):
                if 'For the pop music group' in div.text:
                    anchors = (self._alt_text(a) for a in div.find_all('a', limit=1))
                    _log.debug('Found class=hatnote with text="For the pop music group" - links: {}'.format(anchors))
                    return list(filter(None, anchors))
        return []

    def find_matching_alternative(self, wiki_obj_cls, aliases=None, associated_with=None, reraise=True, client=None):
        fmt = '[reraise={!r}] {} {!r} doesn\'t exist - looking for {} with aliases={!r}, associated_with={!r}; uris: {}'
        uris = ' | '.join(self.alternatives)
        log.debug(fmt.format(reraise, self.obj_type, self.url, wiki_obj_cls.__name__, aliases, associated_with, uris))
        if associated_with and hasattr(wiki_obj_cls, 'find_associated'):    # First since more definitive than aliases
            for alt in self.alternatives:
                try:
                    alt_obj = wiki_obj_cls(alt, client=client)
                except WikiTypeError:
                    pass
                else:
                    try:
                        score, associated_entity = alt_obj.find_associated(associated_with, 95, True)
                    except MemberDiscoveryException:
                        pass
                    else:
                        return alt_obj
        # If no associated act was found, but both were provided, then check aliases too
        if aliases:
            for alt in self.alternatives:
                try:
                    alt_obj = wiki_obj_cls(alt, client=client)
                except WikiTypeError:
                    pass
                else:
                    if alt_obj.matches(aliases):
                        return alt_obj
        # If no match was found, or no identifiers were provided, then re-raise the exception
        if reraise:
            raise self
        return None

    def __repr__(self):
        return '<{}({!r})>: {}'.format(type(self).__name__, self.url, self)

    def __str__(self):
        alts = self.alternative_texts
        base = '{} {!r} doesn\'t exist'.format(self.obj_type, self.url)
        if len(alts) == 1:
            return '{} - did you mean {!r}?'.format(base, alts[0])
        elif alts:
            return '{} - did you mean one of these? {}'.format(base, ' | '.join(alts))
        else:
            return '{} and no suggestions could be found.'.format(base)


class WikiAlbumPartProcessingError(MusicWikiException):
    """Exception to be raised when there's a problem with processing parts of a multi-part album"""


class NoPrimaryArtistError(MusicWikiException):
    """Exception to be raised when retrieving an album's primary artist, but that album has no primary artist"""
