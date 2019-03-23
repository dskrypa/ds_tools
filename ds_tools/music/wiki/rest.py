"""
:author: Doug Skrypa
"""

import logging
import re
import string
from urllib.parse import urlparse

import bs4

from ...caching import cached, DBCache
from ...http import CodeBasedRestException, RestClient
from ...utils import soupify, ParentheticalParser
from .exceptions import *
from .parsing import parse_aside, parse_infobox, parse_album_page, parse_wikipedia_album_page
from .utils import get_page_category

__all__ = ['DramaWikiClient', 'KindieWikiClient', 'KpopWikiClient', 'WikiClient', 'WikipediaClient']
log = logging.getLogger(__name__)

AMBIGUOUS_URI_PATH_TEXT = [
    'This article is a disambiguation page', 'Wikipedia does not have an article with this exact name.',
    'This disambiguation page lists articles associated with'
]
JUNK_CHARS = string.whitespace + string.punctuation
STRIP_TBL = str.maketrans({c: "" for c in JUNK_CHARS})


def http_req_cache_key(self, endpoint, *args, **kwargs):
    params = kwargs.get('params')
    url = self.url_for(endpoint)
    if params:
        return url, tuple(sorted(params.items()))
    return url


class WikiClient(RestClient):
    _site = None
    _sites = {}
    __instances = {}

    def __init_subclass__(cls, **kwargs):  # Python 3.6+
        if cls._site:
            WikiClient._sites[cls._site] = cls

    def __new__(cls, *args, **kwargs):
        if cls.__instances.get(cls) is None:
            cls.__instances[cls] = super().__new__(cls)
        return cls.__instances[cls]

    def __init__(self, host=None, prefix='wiki', proto='https', **kwargs):
        if not getattr(self, '_WikiClient__initialized', False):
            super().__init__(host or self._site, rate_limit=1, prefix=prefix, proto=proto, log_params=True, **kwargs)
            self._resp_cache = DBCache('responses', cache_subdir='kpop_wiki')
            self._name_cache = DBCache('names', cache_subdir='kpop_wiki')
            self._bad_name_cache = DBCache('invalid_names', cache_subdir='kpop_wiki')
            self.__initialized = True

    @classmethod
    def for_site(cls, site):
        try:
            return cls._sites[site]()
        except KeyError as e:
            raise ValueError('No WikiClient class exists for site {!r}'.format(site)) from e

    # @cached('_resp_cache', lock=True, key=lambda s, e, *a, **kw: s.url_for(e), exc=True, optional=True)
    @cached('_resp_cache', lock=True, key=http_req_cache_key, exc=True, optional=True)
    def get(self, *args, **kwargs):
        return super().get(*args, **kwargs)

    @cached(True, exc=True)  # Prevent needing to repeatedly unpickle
    def get_page(self, endpoint, **kwargs):
        return self.get(endpoint, **kwargs).text

    @cached('_name_cache', lock=True, key=lambda s, a: '{}: {}'.format(s.host, a))
    def normalize_name(self, name):
        name = name.strip()
        if not name:
            raise ValueError('A valid name must be provided')
        _name = name
        name = name.replace(' ', '_')
        try:
            html = self.get_page(name)
        except CodeBasedRestException as e:
            if e.code == 404:
                self._bad_name_cache[name] = True
                aae = AmbiguousEntityException(name, e.resp.text)
                alt = aae.alternative
                if alt:
                    if alt.translate(STRIP_TBL).lower() == _name.translate(STRIP_TBL).lower():
                        return alt
                    raise aae from e
                else:
                    try:
                        parts = ParentheticalParser().parse(_name)
                        name = parts[0]
                    except Exception as pe:
                        pass
                    else:
                        log.log(9, 'Checking {!r} for {!r}'.format(name, _name))
                        try:
                            return self._name_cache['{}: {}'.format(self.host, name)]
                        except KeyError as ke:
                            pass

                    # for alt in aae.potential_alternatives:
                    #     if not self._bad_name_cache.get(alt):
                    #         try:
                    #             return self.normalize_name(alt)
                    #         except Exception as ne:
                    #             pass

                    uri_path = self.title_search(name)
                    if uri_path is not None:
                        return uri_path

            raise e
        else:
            if any(val in html for val in AMBIGUOUS_URI_PATH_TEXT):
                raise AmbiguousEntityException(name, html)
            return name

    normalize_artist = normalize_name

    def parse_side_info(self, soup):
        return {}

    def parse_album_page(self, uri_path, clean_soup, side_info):
        return []

    def title_search(self, title):
        raise NotImplementedError()


class KpopWikiClient(WikiClient):
    _site = 'kpop.fandom.com'

    @cached(True)
    def get_entity_base(self, uri_path, obj_type=None):
        raw = self.get_page(uri_path)
        # if 'This article is a disambiguation page' in raw:
        #     raise AmbiguousEntityException(uri_path, raw, obj_type)
        cat_ul = soupify(raw, parse_only=bs4.SoupStrainer('ul', class_='categories'))
        # cat_ul = soupify(raw).find('ul', class_='categories')
        return raw, {li.text.lower() for li in cat_ul.find_all('li')} if cat_ul else set()

    def parse_side_info(self, soup):
        return parse_aside(soup)

    def parse_album_page(self, uri_path, clean_soup, side_info):
        return parse_album_page(uri_path, clean_soup, side_info)

    def title_search(self, title):
        try:
            resp = self.get('Special:Search', params={'query': title})
        except CodeBasedRestException as e:
            log.debug('Error retrieving results for query {!r}: {}'.format(title, e))
            raise e

        lc_title = title.lower()
        results = []
        soup = soupify(resp.text, parse_only=bs4.SoupStrainer('ul', class_='Results'))
        for li in soup.find_all('li', class_='result'):
            a = li.find('a', class_='result-link')
            if a:
                href = a.get('href')
                if href and lc_title in li.text.lower():
                    url = urlparse(href)
                    uri_path = url.path
                    return uri_path[6:] if uri_path.startswith('/wiki/') else uri_path
        return None

    def search(self, query):
        try:
            resp = self.get('Special:Search', params={'query': query})
        except CodeBasedRestException as e:
            log.debug('Error retrieving results for query {!r}: {}'.format(query, e))
            raise e

        results = []
        soup = soupify(resp.text, parse_only=bs4.SoupStrainer('ul', class_='Results'))
        for li in soup.find_all('li', class_='result'):
            a = li.find('a', class_='result-link')
            if a:
                href = a.get('href')
                if href:
                    url = urlparse(href)
                    uri_path = url.path
                    uri_path = uri_path[6:] if uri_path.startswith('/wiki/') else uri_path
                    results.append((a.text, uri_path))
        return results


class KindieWikiClient(KpopWikiClient):
    _site = 'kindie.fandom.com'


class WikipediaClient(WikiClient):
    _site = 'en.wikipedia.org'

    @cached(True)
    def get_entity_base(self, uri_path, obj_type=None):
        raw = self.get_page(uri_path)
        if any(val in raw for val in AMBIGUOUS_URI_PATH_TEXT):
            raise AmbiguousEntityException(uri_path, raw, obj_type)
        cat_links = soupify(raw, parse_only=bs4.SoupStrainer('div', id='mw-normal-catlinks'))
        cat_ul = cat_links.find('ul') if cat_links else None
        cats = {li.text.lower() for li in cat_ul.find_all('li')} if cat_ul else set()
        cat = get_page_category(uri_path, cats, no_debug=True)
        if cat is None and re.search('For other uses, see.*?\(disambiguation\)', raw, re.IGNORECASE):
            raise AmbiguousEntityException(uri_path, raw, obj_type)
        return raw, cats

    def parse_side_info(self, soup):
        return parse_infobox(soup)

    def parse_album_page(self, uri_path, clean_soup, side_info):
        return parse_wikipedia_album_page(uri_path, clean_soup, side_info)

    def search(self, query):
        params = {'search': query, 'title': 'Special:Search', 'fulltext': 'Search'}
        try:
            resp = self.get('index.php', params=params)  #, use_cached=False)
        except CodeBasedRestException as e:
            log.debug('Error retrieving results for query {!r}: {}'.format(query, e))
            raise e

        results = []
        soup = soupify(resp.text, parse_only=bs4.SoupStrainer('ul', class_='mw-search-results'))
        for div in soup.find_all('div', class_='mw-search-result-heading'):
            a = div.find('a')
            if a:
                href = a.get('href')
                if href:
                    url = urlparse(href)
                    uri_path = url.path
                    uri_path = uri_path[6:] if uri_path.startswith('/wiki/') else uri_path
                    results.append((a.text, uri_path))
        return results

    def title_search(self, title):
        params = {'search': title, 'title': 'Special:Search', 'fulltext': 'Search'}
        try:
            resp = self.get('index.php', params=params)#, use_cached=False)
        except CodeBasedRestException as e:
            log.debug('Error searching for title {!r}: {}'.format(title, e))
            raise e

        clean_title = title.translate(STRIP_TBL).lower()
        soup = soupify(resp.text, parse_only=bs4.SoupStrainer('ul', class_='mw-search-results'))
        for a in soup.find_all('a'):
            if a.text.translate(STRIP_TBL).lower() == clean_title:
                href = a.get('href') or ""
                if href and 'redlink=1' not in href:
                    return href[6:] if href.startswith('/wiki/') else href
        return None


class DramaWikiClient(WikiClient):
    _site = 'wiki.d-addicts.com'

    def __init__(self):
        if not getattr(self, '_DramaWikiClient__initialized', False):
            super().__init__(prefix="")
            self.__initialized = True

    @cached(True)
    def get_entity_base(self, uri_path, obj_type=None):
        raw = self.get_page(uri_path)
        cat_links = soupify(raw, parse_only=bs4.SoupStrainer('div', id='mw-normal-catlinks'))
        # cat_links = soupify(raw).find('div', id='mw-normal-catlinks')
        cat_ul = cat_links.find('ul') if cat_links else None
        return raw, {li.text.lower() for li in cat_ul.find_all('li')} if cat_ul else set()

    def search(self, query):
        try:
            resp = self.get('index.php', params={'search': query, 'title': 'Special:Search'})#, use_cached=False)
        except CodeBasedRestException as e:
            log.debug('Error retrieving results for query {!r}: {}'.format(query, e))
            raise e

        results = []
        soup = soupify(resp.text, parse_only=bs4.SoupStrainer('ul', class_='mw-search-results'))
        for div in soup.find_all('div', class_='mw-search-result-heading'):
            a = div.find('a')
            if a:
                href = a.get('href')
                if href:
                    results.append((a.text, urlparse(href).path))
        return results

    def title_search(self, title):
        try:
            resp = self.get('index.php', params={'search': title, 'title': 'Special:Search'})#, use_cached=False)
        except CodeBasedRestException as e:
            log.debug('Error searching for OST {!r}: {}'.format(title, e))
            raise e

        url = urlparse(resp.url)
        if url.path != '/index.php':    # If there's an exact match, it redirects to that page
            return url.path[1:]

        clean_title = title.translate(STRIP_TBL).lower()
        soup = soupify(resp.text, parse_only=bs4.SoupStrainer(class_='searchresults'))
        # for a in soup.find(class_='searchresults').find_all('a'):
        for a in soup.find_all('a'):
            clean_a = a.text.translate(STRIP_TBL).lower()
            if clean_a == clean_title or clean_title in clean_a:
                href = a.get('href') or ""
                if href and 'redlink=1' not in href:
                    return href

        lc_title = title.lower()
        keyword = next((val for val in ('the ', 'a ') if lc_title.startswith(val)), None)
        if keyword:
            return self.title_search(title[len(keyword):].strip())
        return None

    @cached('_name_cache', lock=True, key=lambda s, a: '{}: {}'.format(s.host, a))
    def normalize_name(self, name):
        return self.title_search(name)
