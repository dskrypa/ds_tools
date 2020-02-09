"""
Library for retrieving data from `MediaWiki sites via REST API <https://www.mediawiki.org/wiki/API>`_ or normal
requests.

:author: Doug Skrypa
"""

import json
import logging
import re
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from distutils.version import LooseVersion
from urllib.parse import urlparse

from requests import RequestException

from requests_client import RequestsClient
from ..caching import TTLDBCache, DBCache
from ..core import partitioned
from ..compat import cached_property
from .exceptions import WikiResponseError, PageMissingError
from .page import WikiPage

__all__ = ['MediaWikiClient']
log = logging.getLogger(__name__)
URL_REGEX = re.compile('^[a-zA-Z]+://')


class MediaWikiClient(RequestsClient):
    _siteinfo_cache = None
    _instances = {}

    def __new__(cls, host_or_url, *args, **kwargs):
        host = urlparse(host_or_url).hostname if URL_REGEX.match(host_or_url) else host_or_url
        try:
            return cls._instances[host]
        except KeyError:
            cls._instances[host] = instance = super().__new__(cls)
            return instance

    def __init__(self, host_or_url, *args, ttl=3600 * 6, **kwargs):
        if not getattr(self, '_MediaWikiClient__initialized', False):
            headers = kwargs.get('headers') or {}
            headers.setdefault('Accept', 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8')
            headers.setdefault('Accept-Encoding', 'gzip, deflate')
            headers.setdefault('Accept-Language', 'en-US,en;q=0.5')
            # headers.setdefault('Upgrade-Insecure-Requests', '1')
            if not URL_REGEX.match(host_or_url):
                kwargs.setdefault('scheme', 'https')
            super().__init__(host_or_url, *args, **kwargs)
            if self.host in ('en.wikipedia.org', 'www.generasia.com'):
                self.path_prefix = 'w'
            if MediaWikiClient._siteinfo_cache is None:
                MediaWikiClient._siteinfo_cache = TTLDBCache('siteinfo', cache_subdir='wiki', ttl=3600 * 24)
            self._page_cache = TTLDBCache(f'{self.host}_pages', cache_subdir='wiki', ttl=ttl)
            self._norm_title_cache = DBCache(f'{self.host}_normalized_titles', cache_subdir='wiki', time_fmt='%Y')
            self.__initialized = True

    @cached_property
    def siteinfo(self):
        """Site metadata, including MediaWiki version.  Cached to disk with TTL = 24 hours."""
        try:
            return self._siteinfo_cache[self.host]
        except KeyError:
            params = {'action': 'query', 'format': 'json', 'meta': 'siteinfo', 'siprop': 'general|interwikimap'}
            resp = self.get('api.php', params=params)
            self._siteinfo_cache[self.host] = siteinfo = resp.json()['query']
            return siteinfo

    @cached_property
    def mw_version(self):
        """
        The version of MediaWiki that this site is running.  Used to adjust query parameters due to API changes between
        versions.
        """
        return LooseVersion(self.siteinfo['general']['generator'].split()[-1])

    @cached_property
    def interwiki_map(self):
        rows = self.siteinfo['interwikimap']
        return {row['prefix']: row['url'] for row in rows}

    def interwiki_client(self, iw_map_key):
        try:
            url = self.interwiki_map[iw_map_key]
        except KeyError:
            return None
        else:
            return MediaWikiClient(url, nopath=True)

    @cached_property
    def article_path_prefix(self):
        return self.siteinfo['general']['articlepath'].replace('$1', '')

    def article_url_to_title(self, url):
        return urlparse(url).path.replace(self.article_path_prefix, '', 1)

    def _update_params(self, params):
        """Include useful default parameters, and handle conversion of lists/tuples/sets to pipe-delimited strings."""
        params['format'] = 'json'
        if self.mw_version >= LooseVersion('1.25'):     # https://www.mediawiki.org/wiki/API:JSON_version_2
            params['formatversion'] = 2
        params['utf8'] = 1
        for key, val in params.items():
            # TODO: Figure out U+001F usage when a value containing | is found
            # Docs: If | in value, use U+001F as the separator & prefix value with it, e.g. param=%1Fvalue1%1Fvalue2
            if isinstance(val, (list, tuple, set)):
                params[key] = '|'.join(map(str, val))
                # params[key] = ''.join(map('\u001f{}'.format, val))    # doesn't work for vals without |
        return params

    def query(self, **params):
        """
        Submit, then parse and transform a `query request <https://www.mediawiki.org/wiki/API:Query>`_

        If the response contained a ``continue`` field, then additional requests will be submitted to gather all of the
        results.

        Note: Limit of 50 titles per query, though API docs say the limit for bots is 500

        :param params: Query API parameters
        :return dict: Mapping of {title: dict(results)}
        """
        params['action'] = 'query'
        params['redirects'] = 1
        properties = params.get('prop', [])
        properties = {properties} if isinstance(properties, str) else set(properties)
        if 'iwlinks' in properties:                     # https://www.mediawiki.org/wiki/Special:MyLanguage/API:Iwlinks
            if self.mw_version >= LooseVersion('1.24'):
                params['iwprop'] = 'url'
            else:
                params['iwurl'] = 1
        if 'categories' in properties:              # https://www.mediawiki.org/wiki/Special:MyLanguage/API:Categories
            params['cllimit'] = 500     # default: 10

        titles = params.pop('titles', None)
        if titles:
            # noinspection PyTypeChecker
            if isinstance(titles, str) or len(titles) <= 50:
                return self._query(titles=titles, **params)
            else:
                full_resp = {}
                for group in partitioned(titles, 50):
                    full_resp.update(self._query(titles=group, **params))
                return full_resp
        else:
            return self._query(**params)

    def _query(self, **params):
        params = self._update_params(params)
        resp = self.get('api.php', params=params)
        parsed, more = self._parse_query(resp)
        skip_merge = {'pageid', 'ns', 'title'}
        while more:
            continue_params = params.copy()
            continue_params['prop'] = '|'.join(more.keys())
            for continue_cmd in more.values():
                continue_params.update(continue_cmd)

            resp = self.get('api.php', params=continue_params)
            _parsed, more = self._parse_query(resp)
            for title, data in _parsed.items():
                full = parsed[title]
                for key, val in data.items():
                    if key == 'iwlinks':
                        try:
                            full_val = full[key]
                        except KeyError:
                            full_val = full[key] = defaultdict(dict)  # Mapping of {wiki name: {title: full url}}

                        for iw_name, iw_links in val.items():
                            full_val[iw_name].update(iw_links)
                    else:
                        try:
                            full_val = full[key]
                        except KeyError:
                            full[key] = val
                        else:
                            if isinstance(full_val, list):
                                full_val.extend(val)
                            elif isinstance(full_val, dict):
                                full_val.update(val)
                            elif key in skip_merge:
                                pass
                            else:
                                base = f'Unexpected value to merge for title={title!r} key={key!r} '
                                log.error(f'{base}type={type(full_val).__name__} full_val={full_val!r} new val={val!r}')

        return parsed

    def _parse_query(self, resp):
        response = resp.json()
        if 'query' not in response and 'error' in response:
            raise WikiResponseError(json.dumps(response['error']))

        results = response['query']
        try:
            pages = results['pages']
        except KeyError:
            return response, None
        else:
            redirects = {r['to']: r['from'] for r in results.get('redirects', [])}
            if isinstance(pages, dict):
                pages = pages.values()

            if self.mw_version >= LooseVersion('1.25'):
                iw_key = 'title'
                rev_key = 'content'
            else:
                iw_key, rev_key = '*', '*'

            parsed = {}
            for page in pages:
                title = page['title']
                content = parsed[title] = {'redirected_from': redirects.get(title)}
                for key, val in page.items():
                    if key == 'revisions':
                        content[key] = [rev[rev_key] for rev in val]
                    elif key == 'categories':
                        content[key] = [cat['title'].split(':', maxsplit=1)[1] for cat in val]
                    elif key == 'iwlinks':
                        iwlinks = content[key] = defaultdict(dict)  # Mapping of {wiki name: {title: full url}}
                        for iwlink in val:
                            iwlinks[iwlink['prefix']][iwlink[iw_key]] = iwlink['url']
                    elif key == 'links':
                        content[key] = [link['title'] for link in val]
                    else:
                        content[key] = val
            more = response.get('query-continue')
            return parsed, more

    def parse(self, **params):
        """
        Submit, then parse and transform a `parse request <https://www.mediawiki.org/wiki/API:Parse>`_

        The parse API only accepts one page at a time.

        :param params: Parse API parameters
        :return:
        """
        params['action'] = 'parse'
        params['redirects'] = 1
        properties = params.get('prop', [])
        properties = {properties} if isinstance(properties, str) else set(properties)
        if 'text' in properties:
            params['disabletoc'] = 1
            params['disableeditsection'] = 1

        resp = self.get('api.php', params=self._update_params(params))
        content = {}
        page = resp.json()['parse']
        for key, val in page.items():
            if key in ('wikitext', 'categorieshtml'):
                content[key] = val['*']
            elif key == 'text':
                content['html'] = val['*']
            elif key == 'categories':
                content[key] = [cat['*'] for cat in val]
            elif key == 'iwlinks':
                iwlinks = content[key] = defaultdict(dict)  # Mapping of {wiki name: {title: full url}}
                for iwlink in val:
                    link_text = iwlink['*'].split(':', maxsplit=1)[1]
                    iwlinks[iwlink['prefix']][link_text] = iwlink['url']
            elif key == 'links':
                content[key] = [wl['*'] for wl in val]
            else:
                content[key] = val
        return content

    def query_content(self, titles):
        """Get the contents of the latest revision of one or more pages as wikitext."""
        pages = {}
        resp = self.query(titles=titles, rvprop='content', prop='revisions')
        for title, data in resp.items():
            revisions = data.get('revisions')
            pages[title] = revisions[0] if revisions else None
        return pages

    def query_categories(self, titles):
        """Get the categories of one or more pages."""
        resp = self.query(titles=titles, prop='categories')
        return {title: data.get('categories', []) for title, data in resp.items()}

    def query_pages(self, titles, search=False):
        """
        Get the full page content and the following additional data about each of the provided page titles:\n
          - categories

        Data retrieved by this method is cached in a TTL=1h persistent disk cache.

        If any of the provided titles did not exist, they will not be included in the returned dict.

        Notes:\n
          - The keys in the result may be different than the titles requested
            - Punctuation may be stripped, if it did not belong in the title
            - The case of the title may be different

        :param str|list|set|tuple titles: One or more page titles (as it appears in the URL for the page)
        :param bool search: Whether the provided titles should also be searched for, in case there is not an exact
          match.  This does not seem to work when multiple titles are provided as the search term.
        :return dict: Mapping of {title: dict(page data)}
        """
        if isinstance(titles, str):
            titles = [titles]
        need = []
        pages = {}
        for title in titles:
            try:
                norm_title = self._norm_title_cache[title]
            except KeyError:
                norm_title = title

            try:
                page = self._page_cache[norm_title]
            except KeyError:
                need.append(title)
            else:
                if page:
                    pages[title] = page

        if need:
            kwargs = {'generator': 'search', 'gsrsearch': need, 'gsrwhat': 'nearmatch'} if search else {}
            resp = self.query(titles=need, rvprop='content', prop=['revisions', 'categories'], **kwargs)
            for title, data in resp.items():
                if data.get('pageid') is None:                      # The page does not exist
                    self._page_cache[title] = None
                else:
                    revisions = data.get('revisions')
                    self._page_cache[title] = pages[title] = entry = {
                        'title': title,
                        'categories': data.get('categories', []),
                        'wikitext': revisions[0] if revisions else None
                    }
                    redirected_from = data['redirected_from']
                    if redirected_from:
                        self._norm_title_cache[redirected_from] = title
                        pages[redirected_from] = entry

            if len(pages) == 1 and len(need) == 1:                  # TODO: Add normalized titles for multiple pages
                norm_title, page = next(iter(pages.items()))
                self._norm_title_cache[need[0]] = norm_title
                self._page_cache[need[0]] = page
        return pages

    def query_page(self, title, search=False):
        results = self.query_pages(title, search=search)
        if not results:
            raise PageMissingError(title, self.host)
        elif len(results) == 1:
            return next(iter(results.values()))
        try:
            return results[title]
        except KeyError:
            uc_title = title.upper()
            for key, page in results.items():
                if key.upper() == uc_title:
                    return page
            raise PageMissingError(title, self.host, f'but results were found for: {", ".join(sorted(results))}')

    def parse_page(self, page):
        resp = self.parse(page=page, prop=['wikitext', 'text', 'categories', 'links', 'iwlinks', 'displaytitle'])
        return resp

    def search(self, query, search_type='nearmatch', limit=10, offset=None):
        """
        Search for pages that match the given query.

        `API documentation <https://www.mediawiki.org/wiki/Special:MyLanguage/API:Search>`_

        :param str query: The query
        :param str search_type: The type of search to perform (title, text, nearmatch); some types may be disabled in
          some wikis.
        :param int limit: Number of results to return (max: 500)
        :param int offset: The number of results to skip when requesting additional results for the given query
        :return dict: The parsed response
        """
        params = {
            # 'srprop': ['timestamp', 'snippet', 'redirecttitle', 'categorysnippet']
        }
        if search_type is not None:
            params['srwhat'] = search_type
        if offset is not None:
            params['sroffset'] = offset
        return self.query(list='search', srsearch=query, srlimit=limit, **params)

    def get_pages(self, titles, preserve_comments=False):
        raw_pages = self.query_pages(titles)
        pages = {
            result_title: WikiPage(page['title'], self.host, page['wikitext'], page['categories'], preserve_comments)
            for result_title, page in raw_pages.items()
        }   # The result_title may have redirected to the actual title
        return pages

    def get_page(self, title, preserve_comments=False, search=False):
        page = self.query_page(title, search=search)
        return WikiPage(page['title'], self.host, page['wikitext'], page['categories'], preserve_comments)

    @classmethod
    def page_for_article(cls, article_url, preserve_comments=False):
        client = cls(article_url, nopath=True)
        return client.get_page(client.article_url_to_title(article_url), preserve_comments)

    @classmethod
    def get_multi_site_page(cls, title, sites, preserve_comments=False, search=False):
        """
        :param str title: A page title
        :param iterable sites: A list or other iterable that yields site host strings
        :param bool preserve_comments: Whether HTML comments should be dropped or included in parsed nodes
        :param bool search: Whether the provided title should also be searched for, in case there is not an exact match.
        :return tuple: Tuple containing mappings of {site: WikiPage}, {site: errors}
        """
        clients = [cls(site, nopath=True) for site in sites]
        with ThreadPoolExecutor(max_workers=max(1, len(clients))) as executor:
            _futures = {
                executor.submit(client.get_page, title, preserve_comments, search): client.host for client in clients
            }
            results = {}
            errors = {}
            for future in as_completed(_futures):
                site = _futures[future]
                try:
                    results[site] = future.result()
                except (RequestException, PageMissingError) as e:
                    log.error(f'Error retrieving page={title!r} from site={site}: {e}')
                    errors[site] = e

            return results, errors

    @classmethod
    def get_multi_site_pages(cls, site_title_map, preserve_comments=False):
        """
        :param dict site_title_map: Mapping of {site|MediaWikiCLient: list(titles)}
        :param bool preserve_comments: Whether HTML comments should be dropped or included in parsed nodes
        :return tuple: Tuple containing mappings of {site: results}, {site: errors}
        """
        client_title_map = {
            (site if isinstance(site, cls) else cls(site, nopath=True)): titles
            for site, titles in site_title_map.items()
        }
        with ThreadPoolExecutor(max_workers=max(1, len(client_title_map))) as executor:
            _futures = {
                executor.submit(client.get_pages, titles, preserve_comments): client.host
                for client, titles in client_title_map.items()
            }
            results = {}
            errors = {}
            for future in as_completed(_futures):
                site = _futures[future]
                try:
                    results[site] = future.result()
                except RequestException as e:
                    log.error(f'Error retrieving pages from site={site}: {e}')
                    errors[site] = e

            return results, errors
