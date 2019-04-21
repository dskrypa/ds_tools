"""
:author: Doug Skrypa
"""

import json
import logging
import re
import string
import traceback
from collections import defaultdict
from contextlib import suppress
from itertools import chain
from pathlib import Path
from urllib.parse import urlparse

import bs4

from ...caching import cached, DictAttrProperty, DictAttrPropertyMixin
from ...core import cached_property
from ...http import CodeBasedRestException
from ...unicode import LangCat, romanized_permutations
from ...utils import soupify, normalize_roman_numerals, ParentheticalParser
from ..name_processing import eng_cjk_sort, fuzz_process, parse_name, revised_weighted_ratio, split_name
from .exceptions import *
from .utils import (
    comparison_type_check, edition_combinations, get_page_category, multi_lang_name, sanitize_path, strify_collabs
)
from .rest import WikiClient, KindieWikiClient, KpopWikiClient, WikipediaClient, DramaWikiClient
from .parsing import *

__all__ = [
    'find_ost', 'WikiAgency', 'WikiAlbum', 'WikiArtist', 'WikiDiscography', 'WikiEntity', 'WikiEntityMeta',
    'WikiFeatureOrSingle', 'WikiGroup', 'WikiSinger', 'WikiSongCollection', 'WikiSoundtrack', 'WikiTrack',
    'WikiTVSeries'
]
log = logging.getLogger(__name__)

ALBUM_DATED_TYPES = ('Singles', 'Soundtracks', 'Collaborations', 'Extended Plays')
ALBUM_MULTI_DISK_TYPES = ('Albums', 'Special Albums', 'Japanese Albums', 'Remake Albums', 'Repackage Albums')
ALBUM_NUMBERED_TYPES = ('Album', 'Mini Album', 'Special Album', 'Single Album', 'Remake Album', 'Repackage Album')
DISCOGRAPHY_TYPE_MAP = {
    'best_albums': 'Compilation',
    'collaborations': 'Collaboration',
    'collaborations_and_features': 'Collaboration',
    'collaboration_singles': 'Collaboration',
    'digital_singles': 'Single',
    'eps': 'Extended Play',
    'extended plays': 'Extended Play',
    'features': 'Collaboration',
    'live_albums': 'Live',
    'mini_albums': 'Mini Album',
    'mixtapes': 'Mixtape',
    'osts': 'Soundtrack',
    'other_releases': 'Single',
    'promotional_singles': 'Single',
    'remake_albums': 'Remake Album',    # Album that contains only covers of other artists' songs
    'repackage_albums': 'Album',
    'single_albums': 'Single Album',
    'singles': 'Single',
    'special_albums': 'Special Album',
    'special_singles': 'Single',
    'studio_albums': 'Album'
}
SINGLE_TYPE_TO_BASE_TYPE = {
    None: 'singles',
    'as lead artist': 'singles',
    'collaborations': 'collaborations',
    'as featured artist': 'features',
}
JUNK_CHARS = string.whitespace + string.punctuation
NUM_STRIP_TBL = str.maketrans({c: '' for c in '0123456789'})
NUMS = {
    'first': '1st', 'second': '2nd', 'third': '3rd', 'fourth': '4th', 'fifth': '5th', 'sixth': '6th',
    'seventh': '7th', 'eighth': '8th', 'ninth': '9th', 'tenth': '10th', 'debut': '1st'
}
ROMAN_NUMERALS = {'I': 1, 'II': 2, 'III': 3, 'IV': 4, 'V': 5, 'VI': 6, 'VII': 7, 'VIII': 8, 'IX': 9, 'X': 10}
STRIP_TBL = str.maketrans({c: '' for c in JUNK_CHARS})


class WikiEntityMeta(type):
    _category_classes = {}
    _category_bases = {}
    _instances = {}

    def __init__(cls, name, bases, attr_dict):
        with suppress(AttributeError):
            # noinspection PyUnresolvedReferences
            category = cls._category
            if category is None or isinstance(category, str):
                WikiEntityMeta._category_classes[category] = cls
            else:
                for cat in category:
                    WikiEntityMeta._category_bases[cat] = cls

        super().__init__(name, bases, attr_dict)

    def __call__(
        cls, uri_path=None, client=None, *, name=None, disco_entry=None, no_type_check=False, no_fetch=False,
        of_group=None, aliases=None, **kwargs
    ):
        """
        :param str|None uri_path: The uri path for a page on a wiki
        :param WikiClient|None client: The WikiClient object to use to retrieve the wiki page
        :param str|None name: The name of a WikiEntity to lookup if the uri_path is unknown
        :param dict|None disco_entry: A dict containing information about an album from an Artist's discography section
        :param bool no_type_check: Skip type checks and do not cache the returned object
        :param bool no_fetch: Skip page retrieval
        :param str|WikiGroup of_group: Group that the given name is associated with as a member or sub-unit, or as an
          associated act
        :param aliases: Known aliases for the entity.  If no name or uri_path is provided, the first alias will be
          considered instead.  If a disambiguation page is returned, then aliases help to find the correct match.
        :param kwargs: Additional keyword arguments to pass to the WikiEntity when initializing it
        :return WikiEntity: A WikiEntity (or subclass thereof) based on the provided information
        """
        orig_client = client
        # noinspection PyUnresolvedReferences
        cls_cat = cls._category
        alias_srcs = (name, aliases, disco_entry.get('title') if disco_entry and not no_fetch else None)
        _all_aliases = chain.from_iterable((a,) if isinstance(a, str) else a for a in alias_srcs if a)
        name_aliases = tuple(filter(None, _all_aliases))
        # log.debug('cls({!r}, name={!r}, aliases={!r}): name_aliases={!r}'.format(uri_path, name, aliases, name_aliases))
        if not name_aliases and not uri_path:
            raise WikiEntityIdentificationException('A uri_path or name is required')

        if not no_fetch:
            if disco_entry:
                uri_path = uri_path or disco_entry.get('uri_path')
                disco_site = disco_entry.get('wiki')
                if disco_site and not client:
                    client = WikiClient.for_site(disco_site)
                # elif disco_site and client._site != disco_site:   # Have not seen a need for this yet
                #     fmt = 'Changing client for uri_path={!r} from {} because it has disco_site={!r} specified'
                #     log.log(9, fmt.format(uri_path, client, disco_site))
                #     client = WikiClient.for_site(disco_site)
            elif name_aliases and not uri_path:
                client = client or KpopWikiClient()
                if of_group and not isinstance(of_group, WikiGroup):
                    try:
                        of_group = WikiGroup(aliases=of_group)
                    except WikiTypeError as e:
                        fmt = 'Error initializing WikiGroup(aliases={!r}) for {}(aliases={!r}): {}'
                        log.log(9, fmt.format(of_group, cls.__name__, name_aliases, e))
                    except Exception as e:
                        fmt = 'Error initializing WikiGroup(aliases={!r}) for {}(aliases={!r}): {}'
                        log.debug(fmt.format(of_group, cls.__name__, name_aliases, e))

                if of_group and isinstance(of_group, WikiGroup):
                    return of_group.find_associated(name_aliases)

                key = (uri_path, client, name_aliases)
                obj = WikiEntityMeta._get_match(cls, key, client, cls_cat)  # Does a type check
                if obj is not None:
                    return obj
                elif all(LangCat.contains_any_not(n, LangCat.ENG) for n in name_aliases):
                    if orig_client is None or isinstance(client, KpopWikiClient):
                        clients = (client, KindieWikiClient())
                    else:
                        clients = (client,)
                    return WikiEntityMeta._create_via_search(cls, key, name_aliases, *clients)
                else:
                    exc = None
                    for i, name in enumerate(name_aliases):
                        try:
                            # log.debug('{}: Attempting to normalize {!r}'.format(client, name))
                            uri_path = client.normalize_name(name)
                        except AmbiguousEntityException as e:
                            if e.alternatives:
                                return e.find_matching_alternative(cls, name_aliases, associated_with=of_group)
                            if len(name_aliases) > 1 and i < len(name_aliases):
                                return WikiEntityMeta._create_via_search(cls, key, name_aliases, client)
                        except CodeBasedRestException as e:
                            if e.code == 404:
                                if any(LangCat.contains_any_not(n, LangCat.ENG) for n in name_aliases):
                                    clients = tuple() if orig_client is None else (client,)
                                    # Only needs to run once - uses all name aliases
                                    return WikiEntityMeta._create_via_search(cls, key, name_aliases, *clients)
                                elif orig_client is None:
                                    try:
                                        client = KindieWikiClient()
                                        uri_path = client.normalize_name(name)
                                    except CodeBasedRestException:
                                        client = WikipediaClient()
                                        try:
                                            uri_path = client.normalize_name(name)
                                        except CodeBasedRestException:
                                            fmt = 'Unable to find a page that matches aliases={!r} from any site: {}'
                                            exc = WikiEntityInitException(fmt.format(name_aliases, e))

                            if not uri_path and not exc:
                                exc = e
                        finally:
                            if uri_path:
                                break

                    if not uri_path:
                        if exc:
                            raise exc
                        else:
                            raise WikiEntityInitException('Unable to find a uri_path for {!r}'.format(name_aliases))

            if uri_path and uri_path.startswith(('http://', 'https://', '//')):
                _url = urlparse(uri_path)   # Note: // => alternate subdomain of fandom.com
                if client:
                    fmt = 'Changing client for uri_path={!r} from {} because it is using a different domain'
                    log.log(9, fmt.format(uri_path, client))
                try:
                    client = WikiClient.for_site(_url.hostname)
                except Exception as e:
                    raise WikiEntityInitException('No client configured for {}'.format(_url.hostname)) from e
                uri_path = _url.path[6:] if _url.path.startswith('/wiki/') else _url.path
            elif client is None:
                client = KpopWikiClient()

        if no_type_check or no_fetch:
            # fmt = 'Initializing with no fetch/type_check: {}({!r}, {}, name={!r})'
            # log.debug(fmt.format(cls.__name__, uri_path, client, name))
            obj = cls.__new__(cls, uri_path, client)
            # noinspection PyArgumentList
            obj.__init__(uri_path, client, name=name_aliases, disco_entry=disco_entry, no_fetch=no_fetch, **kwargs)
            return obj

        is_feat_collab = disco_entry and disco_entry.get('base_type') in ('features', 'collaborations', 'singles')
        if uri_path or is_feat_collab:
            uri_path = client.normalize_name(uri_path) if uri_path and ' ' in uri_path else uri_path
            key = (uri_path, client, name_aliases)
            obj = WikiEntityMeta._get_match(cls, key, client, cls_cat)
            if obj is not None:
                return obj
            elif not uri_path and is_feat_collab:
                category, url, raw = 'collab/feature/single', None, None
            else:
                url = client.url_for(uri_path)
                # Note: client.get_entity_base caches args->return vals
                raw, cats = client.get_entity_base(uri_path, cls_cat.title() if isinstance(cls_cat, str) else None)
                category = get_page_category(url, cats)

            # noinspection PyTypeChecker
            WikiEntityMeta._check_type(cls, url, category, cls_cat, raw)
            exp_cls = WikiEntityMeta._category_classes.get(category)
        else:
            exp_cls = cls
            raw = None
            key = (uri_path, client, name_aliases)

        if key not in WikiEntityMeta._instances:
            obj = exp_cls.__new__(exp_cls, uri_path, client)
            # noinspection PyArgumentList
            obj.__init__(uri_path, client, name=name_aliases, raw=raw, disco_entry=disco_entry, **kwargs)
            WikiEntityMeta._instances[key] = obj
            # log.debug('{}: Storing in instance cache with key={}'.format(obj, key), extra={'color': 14})
        else:
            obj = WikiEntityMeta._instances[key]
            # log.debug('{}: Found in instance cache with key={}'.format(obj, key), extra={'color': 10})

        if of_group:
            if isinstance(obj, WikiSinger):
                if obj.member_of is None or not obj.member_of.matches(of_group):
                    fmt = 'Found {} for uri_path={!r}, aliases={!r}, but they are a member_of={}, not of_group={!r}'
                    msg = fmt.format(obj, uri_path, name_aliases, obj.member_of, of_group)
                    raise WikiEntityIdentificationException(msg)
            elif isinstance(obj, WikiGroup):
                if obj.subunit_of is None or not obj.subunit_of.matches(of_group):
                    fmt = 'Found {} for uri_path={!r}, aliases={!r}, but they are a subunit_of={}, not of_group={!r}'
                    msg = fmt.format(obj, uri_path, name_aliases, obj.subunit_of, of_group)
                    raise WikiEntityIdentificationException(msg)
            else:
                raise WikiTypeError('{} is a {}, so cannot be of_group={}'.format(obj, type(obj).__name__, of_group))

        return obj

    @staticmethod
    def _create_via_search(cls, key, name_aliases, *clients):
        clients = clients or (KpopWikiClient(), KindieWikiClient(), WikipediaClient())
        dbg_fmt = 'Search of {} for {!r} yielded non-match: {}'
        # Check 1st 3 results from each site for non-eng name
        for client in clients:
            # log.debug('Attempting search of {} for: {!r}'.format(client._site, '|'.join(all_aliases)))
            for link_text, link_href in client.search('|'.join(name_aliases))[:3]:
                try:
                    entity = cls(link_href, client=client)
                except WikiTypeError as e:
                    log.log(9, dbg_fmt.format(client.host, name_aliases, e))
                else:
                    if entity.matches(name_aliases):
                        WikiEntityMeta._instances[key] = entity
                        WikiEntityMeta._instances[(link_href, client, name_aliases)] = entity
                        return entity
                    else:
                        log.log(9, dbg_fmt.format(client.host, name_aliases, entity))
        else:
            raise WikiEntityIdentificationException('No matches found for {!r} via search'.format(name_aliases))

    @staticmethod
    def _get_match(cls, key, client, cls_cat):
        if key in WikiEntityMeta._instances:
            inst = WikiEntityMeta._instances[key]
            if cls_cat and ((inst._category == cls_cat) or (inst._category in cls_cat)):
                return inst
            else:
                url = client.url_for(inst._uri_path) if inst._uri_path is not None else None
                WikiEntityMeta._check_type(cls, url, inst._category, cls_cat, inst._raw)
        return None

    @staticmethod
    def _check_type(cls, url, category, cls_cat, raw):
        if category == 'disambiguation':
            raise AmbiguousEntityException(url, raw)

        exp_cls = WikiEntityMeta._category_classes.get(category)
        exp_base = WikiEntityMeta._category_bases.get(category)
        has_unexpected_cls = exp_cls and not issubclass(exp_cls, cls) and cls._category is not None
        has_unexpected_base = exp_base and not issubclass(cls, exp_base) and cls._category is not None
        if has_unexpected_cls or has_unexpected_base or (exp_cls is None and exp_base is None):
            article = 'an' if category and category[0] in 'aeiou' else 'a'
            # exp_cls_strs = (getattr(exp_cls, '__name__', None), getattr(exp_base, '__name__', None))
            # log.debug('Specified cls={}, exp_cls={}, exp_base={}'.format(cls.__name__, *exp_cls_strs))
            raise WikiTypeError(url, article, category, cls_cat, cls)


class WikiMatchable:
    _category = None

    def _aliases(self):
        _aliases = (
            getattr(self, attr, None) for attr in ('english_name', 'cjk_name', 'stylized_name', 'name', '_header_title')
        )
        aliases = [a for a in _aliases if a]
        try:
            # noinspection PyUnresolvedReferences
            aka = self.aka
        except AttributeError:
            pass
        else:
            if aka:
                if isinstance(aka, str):
                    aliases.append(aka)
                else:
                    aliases.extend(aka)
        return set(aliases)

    def _additional_aliases(self):
        return set()

    @cached_property
    def aliases(self):
        for attr in ('lc_aliases', '_fuzzed_aliases'):
            try:
                del self.__dict__[attr]
            except KeyError:
                pass

        aliases = self._aliases()
        aliases.update(self._additional_aliases())
        return aliases

    @cached_property
    def lc_aliases(self):
        return [a.lower() for a in self.aliases]

    @cached_property
    def _fuzzed_aliases(self):
        try:
            if isinstance(self, WikiSongCollection):
                return set(filter(None, (fuzz_process(a, strip_special=False) for a in self.aliases)))
            return set(filter(None, (fuzz_process(a) for a in self.aliases)))
        except Exception as e:
            log.error('{}: Error fuzzing aliases: {}'.format(self, self.aliases))
            raise e

    def matches(self, other, process=True):
        """
        Checks to see if one of the given strings is an exact match (after processing to remove spaces, punctuation,
        etc) for one of this entity's aliases (which undergo the same processing).  If passed a WikiEntity object, a
        basic equality test is performed instead.

        :param str|Iterable|WikiEntity other: The object to match against
        :param bool process: Run :func:`fuzz_process<.music.name_processing.fuzz_process>` on strings before comparing
          them (should only be set to False if the strings were already processed)
        :return bool: True if one of the given strings is an exact match for this entity, False otherwise
        """
        if isinstance(other, WikiEntity):
            # log.debug('Comparing {} [{}] to other={} [{}]'.format(self, self.url, other, other.url))
            return self.score_match(other)[0] >= 100
            # return self == other
        # log.debug('Comparing {} [{}] to other={}'.format(self, self.url, other))
        others = (other,) if isinstance(other, str) else filter(None, other)
        fuzzed_others = tuple(filter(None, (fuzz_process(o) for o in others) if process else others))
        if not fuzzed_others:
            log.warning('Unable to compare {} to {!r}: nothing to compare after processing'.format(self, other))
            return False
        return bool(self._fuzzed_aliases.intersection(fuzzed_others))

    def score_match(self, other, process=True, track=None, disk=None, year=None, track_count=None):
        """
        Score how closely this WikiEntity's aliases match the given strings.

        :param str|Iterable other: String or iterable that yields strings
        :param bool process: Run :func:`fuzz_process<.music.name_processing.fuzz_process>` on strings before comparing
          them (should only be set to False if the strings were already processed)
        :param int|None track: The track number if other represents a track
        :param int|none disk: The disk number if other represents a track
        :param int|None year: The release year if other represents an album
        :return tuple: (score, best alias of this WikiEntity, best value from other)
        """
        eng, cjk = None, None
        if not isinstance(other, (str, WikiEntity)) and len(other) == 1:
            other = other[0]
        if isinstance(other, str):
            lang = LangCat.categorize(other)
            if lang == LangCat.MIX:
                try:
                    eng, cjk = split_name(other)
                except ValueError:
                    others = (other,)
                else:
                    others = (eng, cjk)
                    if others[0].lower() == 'live':
                        others = (other,)
            elif lang == LangCat.HAN:
                cjk = other
                others = romanized_permutations(other)
                others.insert(0, other)
            else:
                if lang in LangCat.asian_cats:
                    cjk = other
                others = (other,)
        elif isinstance(other, WikiEntity):
            if self._category != other._category and self._category is not None and other._category is not None:
                log.warning('Unable to compare {} to {!r}: incompatible categories'.format(self, other))
                return 0, None, None
            others = other._fuzzed_aliases
            process = False
        else:
            others = other

        if isinstance(self, WikiSongCollection):
            fuzzed_others = tuple(filter(None, (fuzz_process(o, strip_special=False) for o in others) if process else others))
        else:
            fuzzed_others = tuple(filter(None, (fuzz_process(o) for o in others if o) if process else others))
        if not fuzzed_others:
            log.warning('Unable to compare {} to {!r}: nothing to compare after processing'.format(self, other))
            return 0, None, None

        # scorer = fuzz.WRatio if isinstance(self, WikiSongCollection) else fuzz.token_sort_ratio
        scorer = revised_weighted_ratio

        score_mod = 0
        if track is not None and isinstance(self, WikiTrack):
            score_mod += 15 if str(self.num) == str(track) else -15
        if disk is not None and isinstance(self, WikiTrack):
            score_mod += 15 if str(self.disk) == str(disk) else -15
        if isinstance(self, WikiTrack):
            self_has_inst = 'inst' in self.long_name.lower()
            if isinstance(other, str):
                other_has_inst = 'inst' in other.lower()
            else:
                other_has_inst = any('inst' in other for other in fuzzed_others)
            if (self_has_inst and not other_has_inst) or (not self_has_inst and other_has_inst):
                # other_repr = other if isinstance(other, WikiEntity) else others
                # log.debug('{!r}=?={!r}: score_mod-=25 (no inst)'.format(self, other_repr))
                score_mod -= 25

        if isinstance(self, WikiSongCollection):
            if year is not None:
                try:
                    years_match = str(self.released.year) == str(year)
                except Exception:
                    pass
                else:
                    score_mod += 15 if years_match else -15
            if track_count is not None:
                try:
                    track_counts_match = len(self.get_tracks()) == track_count
                except Exception:
                    pass
                else:
                    score_mod += 20 if track_counts_match else -20

        best_score, best_alias, best_val = 0, None, None
        for alias in self._fuzzed_aliases:
            for val in fuzzed_others:
                if best_score >= 100:
                    break
                # score = scorer(alias, val, force_ascii=False, full_process=False)
                score = scorer(alias, val)
                if ('live' in alias and 'live' not in val) or ('live' in val and 'live' not in alias):
                    score -= 25

                # other_repr = other if isinstance(other, WikiEntity) else val
                # log.debug('{!r}=?={!r}: score={}, alias={!r}, val={!r}'.format(self, other_repr, score, alias, val))
                if score > best_score:
                    best_score, best_alias, best_val = score, alias, val

        final_score = best_score + score_mod
        if final_score >= 100 and cjk and not getattr(self, 'cjk_name', None):
            log.debug('Updating {!r}.cjk_name => {!r}'.format(self, cjk))
            try:
                self.update_name(None, cjk)
            except AttributeError:
                pass

        return final_score, best_alias, best_val


class WikiEntity(WikiMatchable, metaclass=WikiEntityMeta):
    __instances = {}
    _categories = {}
    _category = None

    def __init__(self, uri_path=None, client=None, *, name=None, raw=None, no_fetch=False, **kwargs):
        if uri_path is None and name is None and raw is None:
            raise WikiEntityInitException('Unable to initialize a {} with no identifiers'.format(type(self).__name__))
        self.__additional_aliases = set()
        self._client = client
        self._uri_path = uri_path
        self._raw = raw if raw is not None else client.get_page(uri_path) if uri_path and not no_fetch else None
        self.english_name = None
        self.cjk_name = None
        if not name:
            self.name = uri_path
        elif isinstance(name, str):
            self.name = name
        else:
            if len(name) == 2:
                try:
                    self.update_name(*eng_cjk_sort(name))
                except ValueError as e:
                    self.name = name[0]
                    self._add_alias(name[1])
            else:
                self.name = name[0]
                self._add_aliases(name[1:])

        if isinstance(self._client, DramaWikiClient) and self._raw:
            self._header_title = soupify(self._raw, parse_only=bs4.SoupStrainer('h2', class_='title')).text
        else:
            self._header_title = None

    def update_name(self, eng_name, cjk_name):
        self.english_name = normalize_roman_numerals(eng_name) if eng_name else self.english_name
        self.cjk_name = normalize_roman_numerals(cjk_name) if cjk_name else self.cjk_name
        self.name = multi_lang_name(self.english_name, self.cjk_name)
        try:
            del self.__dict__['aliases']
        except KeyError:
            pass

    def __repr__(self):
        return '<{}({!r})>'.format(type(self).__name__, self.name)

    def __eq__(self, other):
        if not isinstance(other, WikiEntity):
            return False
        return self.name == other.name and self._raw == other._raw

    def __hash__(self):
        return hash((self.name, self._raw))

    def _add_alias(self, alias):
        self.__additional_aliases.add(alias)
        try:
            del self.__dict__['aliases']
        except KeyError:
            pass

    def _add_aliases(self, aliases):
        self.__additional_aliases.update(aliases)
        try:
            del self.__dict__['aliases']
        except KeyError:
            pass

    def _additional_aliases(self):
        return self.__additional_aliases

    @cached_property
    def url(self):
        if self._uri_path is None:
            return None
        return self._client.url_for(self._uri_path)

    @property
    def _soup(self):
        # soupify every time so that elements may be modified/removed without affecting other functions
        return soupify(self._raw, parse_only=bs4.SoupStrainer('div', id='mw-content-text')) if self._raw else None

    @cached_property
    def _side_info(self):
        """The parsed 'aside' / 'infobox' section of this page"""
        if not hasattr(self, '_WikiEntity__side_info'):
            _ = self._clean_soup

        try:
            return {} if not self.__side_info else self._client.parse_side_info(self.__side_info, self._uri_path)
        except Exception as e:
            log.error('Error processing side bar info for {}: {}'.format(self._uri_path, e))
            raise e

    @cached_property
    def _clean_soup(self):
        """The soupified page content, with the undesirable parts at the beginning removed"""
        try:
            content = self._soup.find('div', id='mw-content-text')
        except AttributeError as e:
            self.__side_info = None
            if self._soup is not None:
                log.warning(e)
            return None

        if isinstance(self._client, (KpopWikiClient, KindieWikiClient)):
            aside = content.find('aside')
            # if aside:
            #     log.debug('Extracting aside')
            self.__side_info = aside.extract() if aside else None

            for ele_name in ('center',):
                rm_ele = content.find(ele_name)
                if rm_ele:
                    # log.debug('Extracting: {}'.format(rm_ele))
                    rm_ele.extract()

            for clz in ('dablink', 'hatnote', 'shortdescription', 'infobox'):
                rm_ele = content.find(class_=clz)
                if rm_ele:
                    # log.debug('Extracting: {}'.format(rm_ele))
                    rm_ele.extract()

            for rm_ele in content.find_all(class_='mw-empty-elt'):
                # log.debug('Extracting: {}'.format(rm_ele))
                rm_ele.extract()

            first_ele = content.next_element
            if getattr(first_ele, 'name', None) == 'dl':
                # log.debug('Extracting: {}'.format(first_ele))
                first_ele.extract()
        elif isinstance(self._client, DramaWikiClient):
            self.__side_info = None
            for clz in ('toc',):
                rm_ele = content.find(class_=clz)
                if rm_ele:
                    rm_ele.extract()

            for clz in ('toc', 'mw-editsection'):
                for rm_ele in content.find_all(class_=clz):
                    rm_ele.extract()
        elif isinstance(self._client, WikipediaClient):
            for rm_ele in content.select('[style~="display:none"]'):
                rm_ele.extract()

            infobox = content.find('table', class_=re.compile('infobox.*'))
            self.__side_info = infobox.extract() if infobox else None

            for rm_ele in content.find_all(class_='mw-empty-elt'):
                rm_ele.extract()

            for clz in ('toc', 'mw-editsection', 'reference', 'hatnote', 'infobox', 'noprint'):
                for rm_ele in content.find_all(class_=clz):
                    rm_ele.extract()

            for clz in ('shortdescription', 'box-More_citations_needed'):
                rm_ele = content.find(class_=clz)
                if rm_ele:
                    rm_ele.extract()
        else:
            log.debug('No sanitization configured for soup objects from {}'.format(type(self._client).__name__))
        return content

    @cached_property
    def _all_anchors(self):
        return list(self._clean_soup.find_all('a'))

    def _has_no_valid_links(self, href, text):
        if not href and self._raw:
            # fmt = '{}: Seeing if text={!r} == anchor={!r} => a.text={!r}, a.class={!r}, a.href={!r}'
            for a in self._all_anchors:
                _href = a.get('href')
                # log.debug(fmt.format(self.url, text, a, a.text, a.get('class'), _href))
                if a.text == text:
                    if _href and '&redlink=1' not in _href:             # a valid link
                        return False
                    elif 'new' in a.get('class') and _href is None:     # displayed as a red link in a browser
                        return True
                elif _href:
                    _url = urlparse(_href[6:] if _href.startswith('/wiki/') else _href)
                    if _url.path == text:
                        return '&redlink=1' in _url.query
        elif href and '&redlink=1' in href:
            return True
        return False


class WikiAgency(WikiEntity):
    _category = 'agency'


class WikiDiscography(WikiEntity):
    _category = 'discography'

    def __init__(self, uri_path=None, client=None, *, artist=None, **kwargs):
        super().__init__(uri_path, client, **kwargs)
        self.artist = artist
        self._albums, self._singles = parse_discography_page(self._uri_path, self._clean_soup, artist)


class WikiTVSeries(WikiEntity):
    _category = 'tv_series'

    def __init__(self, uri_path=None, client=None, **kwargs):
        super().__init__(uri_path, client, **kwargs)
        self.ost_hrefs = []
        if self._side_info:
            self.name = self._side_info['name']
            self.aka = self._side_info.get('also known as', [])
        elif isinstance(self._client, DramaWikiClient):
            self.name = self._header_title
            if self._raw:
                info_header = self._clean_soup.find(id='Details') or self._clean_soup.find(id='Season_1')
                try:
                    ul = info_header.parent.find_next('ul')
                except Exception as e:
                    raise WikiEntityParseException('Unable to find info for {} from {}'.format(self, self.url)) from e

                self._info = parse_drama_wiki_info_list(self._uri_path, ul, client)
                try:
                    self.english_name, self.cjk_name = self._info['title']
                except ValueError as e:
                    err_msg = 'Unexpected show title for {}: {!r}'.format(self.url, self._info['title'])
                    title = self._info['title']
                    if isinstance(title, str) and LangCat.contains_any_not(title, LangCat.ENG):
                        romaji = self._info.get('title (romaji)')
                        if romaji and LangCat.categorize(romaji) == LangCat.ENG:
                            self.english_name = romaji
                            self.cjk_name = title
                        else:
                            log.error(err_msg)
                    else:
                        log.error(err_msg)

                if self._header_title and LangCat.categorize(self._header_title) == LangCat.ENG:
                    if self.english_name and self.cjk_name and self.english_name != self._header_title:
                        permutations = {''.join(p.split()) for p in romanized_permutations(self.cjk_name)}
                        if ''.join(self.english_name.lower().split()) in permutations:
                            self._add_alias(self.english_name)
                            self.english_name = self._header_title
                    elif self.cjk_name and not self.english_name:
                        self.english_name = self._header_title

                if self.english_name and self.cjk_name:
                    self.name = multi_lang_name(self.english_name, self.cjk_name)
                self.aka = self._info.get('also known as', [])
                ost = self._info.get('original soundtrack') or self._info.get('original soundtracks')
                if ost:
                    self.ost_hrefs.append(list(ost.values())[0])

                ost_tag_func = lambda tag: tag.name == 'li' and tag.text.lower().startswith('original soundtrack')
                try:
                    for li in self._clean_soup.find_all(ost_tag_func):
                        href = li.find('a').get('href')
                        if href and href not in self.ost_hrefs:
                            self.ost_hrefs.append(href)
                except Exception as e:
                    msg = 'Error processing OST links for {} from {}'.format(self, self.url)
                    raise WikiEntityParseException(msg) from e
        else:
            self.aka = []


class WikiArtist(WikiEntity):
    _category = ('group', 'singer')
    _known_artists = set()
    __known_artists_loaded = False

    def __init__(self, uri_path=None, client=None, *, name=None, strict=True, **kwargs):
        super().__init__(uri_path, client, name=name, **kwargs)
        self.english_name, self.cjk_name, self.stylized_name, self.aka = None, None, None, None
        if self._raw and not kwargs.get('no_init'):
            if isinstance(self._client, DramaWikiClient):
                ul = self._clean_soup.find(id='Profile').parent.find_next('ul')
                self._profile = parse_drama_wiki_info_list(self._uri_path, ul, client)
                self.english_name, self.cjk_name = self._profile.get('name', self._profile.get('group name'))
                # If eng name has proper eng name + romanized hangul name, remove the romanized part
                if self.english_name and self.cjk_name and '(' in self.english_name and self.english_name.endswith(')'):
                    m = re.match(r'^(.*)\((.*)\)$', self.english_name)
                    if m:
                        lc_nospace_rom = ''.join(m.group(1).lower().split())
                        for permutation in romanized_permutations(self.cjk_name):
                            if ''.join(permutation.split()) == lc_nospace_rom:
                                self.english_name = m.group(2).strip()
                                break
            elif isinstance(self._client, WikipediaClient):
                self.english_name = self._side_info['name']
            else:
                try:
                    name_parts = parse_name(self._clean_soup.text)
                except Exception as e:
                    fmt = '{} while processing intro for {}: {}'
                    log.warning(fmt.format(type(e).__name__, self._client.url_for(uri_path), e))
                    if strict:
                        raise e
                else:
                    self.english_name, self.cjk_name, self.stylized_name, self.aka, self._info = name_parts

        if name and not any(val for val in (self.english_name, self.cjk_name, self.stylized_name)):
            self.english_name, self.cjk_name = split_name(name)

        self.name = multi_lang_name(self.english_name, self.cjk_name)
        if self.english_name and isinstance(self._client, KpopWikiClient):
            type(self)._known_artists.add(self.english_name.lower())

        self._albums, self._singles = None, None

    def __repr__(self):
        try:
            return '<{}({!r})>'.format(type(self).__name__, self.stylized_name or self.qualname)
        except AttributeError as e:
            return '<{}({!r})>'.format(type(self).__name__, self._uri_path)

    def __lt__(self, other):
        comparison_type_check(self, other, (WikiArtist, str), '<')
        return (self.name < other.name) if isinstance(other, WikiArtist) else (self.name < other)

    def __gt__(self, other):
        comparison_type_check(self, other, (WikiArtist, str), '>')
        return (self.name > other.name) if isinstance(other, WikiArtist) else (self.name > other)

    @classmethod
    def known_artist_eng_names(cls):
        if not cls.__known_artists_loaded:
            cls.__known_artists_loaded = True
            known_artists_path = Path(__file__).resolve().parents[3].joinpath('music/artist_dir_to_artist.json')
            with open(known_artists_path.as_posix(), 'r', encoding='utf-8') as f:
                artists = json.load(f)
            cls._known_artists.update((split_name(artist)[0].lower() for artist in artists.values()))
        return cls._known_artists

    @classmethod
    def known_artists(cls):
        for name in sorted(cls.known_artist_eng_names()):
            yield WikiArtist(name=name)

    @cached(True, lock=True)
    def for_alt_site(self, site_or_client):
        client = WikiClient.for_site(site_or_client) if isinstance(site_or_client, str) else site_or_client
        if self._client._site == client._site:
            return self
        try:
            candidate = type(self)(name=self.english_name or self.cjk_name, client=client)
        except CodeBasedRestException as e:
            pass
        else:
            if candidate._uri_path and candidate._raw:
                candidate._add_aliases(self.aliases)
                self._add_aliases(candidate.aliases)
                if self.english_name and self.cjk_name and (not candidate.english_name or not candidate.cjk_name):
                    candidate.update_name(self.english_name, self.cjk_name)
                elif candidate.english_name and candidate.cjk_name and (not self.english_name or not self.cjk_name):
                    self.update_name(candidate.english_name, candidate.cjk_name)
                return candidate

        # log.debug('{}: Could not find {} version by name'.format(self, client))
        for i, (text, uri_path) in enumerate(client.search('|'.join(sorted(self.aliases)))):
            candidate = type(self)(uri_path, client=client)
            # log.debug('{}: Validating candidate={}'.format(self, candidate))
            if candidate.matches(self):
                candidate._add_aliases(self.aliases)
                self._add_aliases(candidate.aliases)
                if self.english_name and self.cjk_name and (not candidate.english_name or not candidate.cjk_name):
                    candidate.update_name(self.english_name, self.cjk_name)
                elif candidate.english_name and candidate.cjk_name and (not self.english_name or not self.cjk_name):
                    self.update_name(candidate.english_name, candidate.cjk_name)
                return candidate
            elif i > 4:
                break

        raise WikiEntityInitException('Unable to find valid {} version of {}'.format(client, self))

    @cached_property
    def _alt_entities(self):
        pages = []
        for client_cls in (KpopWikiClient, WikipediaClient):
            if not isinstance(self._client, client_cls):
                try:
                    page = WikiArtist(None, client_cls(), name=self._uri_path)
                except Exception as e:
                    log.debug('Unable to retrieve alternate {} entity for {}: {}'.format(client_cls.__name__, self, e))
                else:
                    pages.append(page)
        return pages

    @cached_property
    def _disco_page(self):
        if self._albums or self._singles:
            return self
        elif not isinstance(self._client, WikipediaClient):
            site = WikipediaClient._site
            try:
                alt_artist = self.for_alt_site(site)
            except Exception as e:
                log.debug('{}: Error finding {} version: {}'.format(self, site, e))
            else:
                return alt_artist._disco_page
        elif isinstance(self._client, WikipediaClient):
            disco_links = set()
            for a in self._soup.find_all('a'):
                a_text = a.text.lower() if a.text else ''
                if 'discography' in a_text:
                    href = a.get('href') or ''
                    href = href[6:] if href.startswith('/wiki/') else href
                    remaining = ''.join(a_text.partition('discography')[::2]).strip()
                    if href and '#' not in href and (not remaining or self.matches(remaining)):
                        disco_links.add(href)
            if disco_links:
                if len(disco_links) == 1:
                    uri_path = disco_links.pop()
                    client = WikipediaClient()
                    try:
                        try:
                            return WikiDiscography(uri_path, client, artist=self)
                        except WikiTypeError as e:
                            return WikiArtist(uri_path, client)
                    except Exception as e:
                        fmt = '{}: Error retrieving discography page {}: {}'
                        log.error(fmt.format(self, client.url_for(uri_path), e))
                else:
                    fmt = '{}: Too many different discography links found: {}'
                    log.error(fmt.format(self, ', '.join(sorted(disco_links))), extra={'color': 'yellow'})
        return None

    @property
    def _discography(self):
        if self._albums:            # Will only be set for non-kwiki sources
            return self._albums
        elif isinstance(self._client, KpopWikiClient):
            return parse_discography_section(self, self._clean_soup)
        elif isinstance(self._client, WikipediaClient):   # Pretend to be a WikiDiscography when both are on same page
            try:
                self._albums, self._singles = parse_discography_page(self._uri_path, self._clean_soup, self)
            except Exception:
                disco_page = self._disco_page
                if disco_page:
                    self._albums, self._singles = disco_page._albums, disco_page._singles
        elif isinstance(self._client, DramaWikiClient):
            try:
                self._albums = parse_artist_osts(self._uri_path, self._clean_soup, self)
            except WikiEntityParseException as e:
                log.debug('{}: Error parsing discography from {}: {}'.format(self, self.url, e))
                self._albums = None

        if self._albums:
            return self._albums

        log.debug('{}: No discography content could be found from {}'.format(self, getattr(self._client, 'host', None)))
        return []

    @cached_property
    def discography(self):
        discography = []
        for entry in self._discography:
            if entry['is_ost'] and not (entry.get('wiki') == 'wiki.d-addicts.com' and entry.get('uri_path')):
                client = WikiClient.for_site('wiki.d-addicts.com')
                title = entry['title']
                m = re.match('^(.*)\s+(?:Part|Code No)\.?\s*\d+$', title, re.IGNORECASE)
                if m:
                    title = m.group(1).strip()
                uri_path = client.normalize_name(title)
                # log.debug('Normalized title={!r} => uri_path={!r}'.format(title, uri_path))
            else:
                client = WikiClient.for_site(entry['wiki'])
                uri_path = entry['uri_path']
                title = entry['title']

            cls = WikiSongCollection
            if not uri_path:
                base_type = entry.get('base_type')
                if base_type == 'osts':
                    cls = WikiSoundtrack
                elif any(val in base_type for val in ('singles', 'collaborations', 'features')):
                    cls = WikiFeatureOrSingle
                elif any(val in base_type for val in ('albums', 'eps', 'extended plays')):
                    cls = WikiAlbum
                else:
                    log.debug('{}: Unexpected base_type={!r} for {}'.format(self, base_type, entry), extra={'color': 9})

            try:
                try:
                    discography.append(cls(uri_path, client, disco_entry=entry, artist_context=self))
                except WikiTypeError as e:
                    if isinstance(client, DramaWikiClient):
                        if e.category == 'tv_series':
                            series = WikiTVSeries(uri_path, client)
                            found = False
                            if series.ost_hrefs:
                                for ost_href in series.ost_hrefs:
                                    ost = WikiSongCollection(ost_href, client, disco_entry=entry, artist_context=self)
                                    if len(series.ost_hrefs) == 1 or ost.matches(title):
                                        discography.append(ost)
                                        found = True
                                        break
                            if not found:
                                fmt = '{}: Error processing discography entry in {} for {!r} / {!r}: {}'
                                msg = fmt.format(self, self.url, entry['uri_path'], entry['title'], e)
                                log.error(msg, extra={'color': 13})
                    else:
                        fmt = '{}: Error processing discography entry in {} for {!r} / {!r}: {}'
                        log.error(fmt.format(self, self.url, entry['uri_path'], entry['title'], e), extra={'color': 13})
                except CodeBasedRestException as http_e:
                    if entry['is_ost'] and not isinstance(self._client, DramaWikiClient):
                        ost = find_ost(self, title, entry)
                        if ost:
                            discography.append(ost)
                        else:
                            log.log(9, '{}: Unable to find wiki page or alternate matches for {}'.format(self, entry))
                            ost = cls(uri_path, client, disco_entry=entry, artist_context=self, no_fetch=True)
                            discography.append(ost)
                            # raise http_e
                    else:
                        url = client.url_for(uri_path, allow_alt_sites=True)
                        if urlparse(url).hostname != self._client.host:
                            log.debug('{}: {} has a bad link for {} to {}'.format(self, self.url, entry['title'], url))
                        else:
                            fmt = '{}: Unable to find wiki page for {} via {}\n{}'
                            log.debug(fmt.format(self, entry, url, traceback.format_exc()))
                        alb = cls(uri_path, client, disco_entry=entry, artist_context=self, no_fetch=True)
                        discography.append(alb)
                        # raise http_e
            except MusicWikiException as e:
                fmt = '{}: Error processing discography entry in {} for {!r} / {!r}: {}\n{}'
                msg = fmt.format(self, self.url, entry['uri_path'], entry['title'], e, traceback.format_exc())
                log.error(msg, extra={'color': 13})
                # raise e

        if self._singles:
            for group in self._singles:
                group_type = group['type']
                group_sub_type = group['sub_type']
                if group_type in ('other charted songs', ):
                    continue
                elif any('soundtrack' in (group.get(k) or '') for k in ('sub_type', 'type')):
                    soundtracks = defaultdict(list)
                    for track in group['tracks']:
                        soundtracks[track['album']].append(track)

                    for ost_name, tracks in soundtracks.items():
                        disco_entry = {'title': ost_name, 'is_ost': True, 'track_info': tracks, 'base_type': 'osts'}
                        album_info = {
                            'track_lists': [{'section': None, 'tracks': tracks}], 'num': None, 'type': 'OST',
                            'repackage': False, 'length': None, 'released': None, 'links': []
                        }
                        alb = WikiSoundtrack(
                            None, self._client, no_type_check=True, disco_entry=disco_entry, album_info=album_info,
                            artist_context=self
                        )
                        discography.append(alb)
                else:
                    for track in group['tracks']:
                        name = track['name_parts']

                        collabs = set(track.get('collaborators', []))
                        collabs.update(l[0] for l in track.get('links', []))
                        collabs = [{'artist': eng_cjk_sort(collab)} for collab in collabs]

                        track['collaborators'] = collabs
                        try:
                            disco_entry = {
                                'title': name, 'collaborators': collabs,
                                'base_type': SINGLE_TYPE_TO_BASE_TYPE[group_sub_type]
                            }
                        except KeyError as e:
                            err_msg = '{}: Unexpected single sub_type={!r} on {}'.format(self, group_sub_type, self.url)
                            raise WikiEntityParseException(err_msg) from e

                        # fmt = '{}: Adding single type={!r} subtype={!r} name={!r} collabs={}'
                        # log.debug(fmt.format(self, group_type, group_sub_type, name, collabs))

                        # disco_entry = {'title': name}
                        album_info = {'track_lists': [{'section': None, 'tracks': [track]}]}
                        single = WikiFeatureOrSingle(
                            None, self._client, disco_entry=disco_entry, album_info=album_info, artist_context=self,
                            no_fetch=True, name=name
                        )
                        discography.append(single)
        return discography

    @cached_property
    def soundtracks(self):
        return [album for album in self.discography if isinstance(album, WikiSoundtrack)]

    @cached()
    def expected_rel_path(self):
        return Path(sanitize_path(self.english_name))

    @cached_property
    def associated_acts(self):
        associated = []
        for text, href in self._side_info.get('associated', {}).items():
            # log.debug('{}: Associated act from {}: a.text={!r}, a.href={!r}'.format(self, self.url, text, href))
            associated.append(WikiArtist(href, name=text, client=self._client))
        return associated

    def find_song_collection(self, name, min_score=75, include_score=False, **kwargs):
        if isinstance(name, str):
            if name.lower().startswith('full album'):
                name = (name, name[10:].strip())
        match_fmt = '{}: {} matched {!r} with score={} because its alias={!r} =~= {!r}'
        best_score, best_alias, best_val, best_coll = 0, None, None, None
        for collection in self.discography:
            score, alias, val = collection.score_match(name, **kwargs)
            if score >= 100:
                # log.debug(match_fmt.format(self, collection, name, score, alias, val))
                return (collection, score) if include_score else collection
            elif score > best_score:
                best_score, best_alias, best_val, best_coll = score, alias, val, collection

        if best_score > min_score:
            if best_score < 95:
                log.debug(match_fmt.format(self, best_coll, name, best_score, best_alias, best_val))
            return (best_coll, best_score) if include_score else best_coll
        elif isinstance(self._client, KpopWikiClient):
            site = WikipediaClient._site
            try:
                alt_artist = self.for_alt_site(site)
            except Exception as e:
                log.debug('{}: Error finding {} version: {}'.format(self, site, e))
            else:
                return alt_artist.find_song_collection(name, min_score=min_score, include_score=include_score, **kwargs)

        aliases = (name,) if isinstance(name, str) else name
        if isinstance(self._client, (KpopWikiClient, WikipediaClient)) and any('OST' in a.upper() for a in aliases):
            site = DramaWikiClient._site
            try:
                alt_artist = self.for_alt_site(site)
            except Exception as e:
                log.debug('{}: Error finding {} version: {}'.format(self, site, e))
            else:
                return alt_artist.find_song_collection(name, min_score=min_score, include_score=include_score, **kwargs)

        return (None, -1) if include_score else None

    def find_track(
        self, track_name, album_name=None, min_score=75, include_score=False, track=None, disk=None, year=None, **kwargs
    ):
        year = str(year) if year else year
        # alb_name_langs = LangCat.categorize(album_name, True) if album_name else set()

        best_score, best_track, best_coll = 0, None, None
        for collection in self.discography:
            track, score = collection.find_track(
                track_name, min_score=min_score, include_score=True, track=track, disk=disk, **kwargs
            )
            if score > 0:
                collection = track.collection
                if year and collection.year:
                    score += 15 if str(collection.year) == year else -15
                if album_name:
                    if collection.matches(album_name):
                        score += 15

                if score > best_score:
                    best_score, best_track, best_coll = score, track, collection

        if best_score > min_score:
            if best_score < 95:
                if album_name:
                    match_fmt = '{}: {} from {} matched {!r} from {!r} with score={}'
                    log.debug(match_fmt.format(self, best_track, best_coll, track_name, album_name, best_score))
                else:
                    match_fmt = '{}: {} from {} matched {!r} with score={}'
                    log.debug(match_fmt.format(self, best_track, best_coll, track_name, best_score))
            return (best_track, best_score) if include_score else best_track
        elif isinstance(self._client, KpopWikiClient):
            site = WikipediaClient._site
            try:
                alt_artist = self.for_alt_site(site)
            except Exception as e:
                log.debug('{}: Error finding {} version: {}'.format(self, site, e))
            else:
                return alt_artist.find_track(
                    track_name, album_name, min_score=min_score, include_score=include_score, track=track, disk=disk,
                    year=year, **kwargs
                )

        return (None, -1) if include_score else None

    @cached_property
    def qualname(self):
        """Like an FQDN for artists - if this is a WikiSinger, include the group they are a member of"""
        return self.name

    def _as_collab(self):
        return {'artist': (self.english_name, self.cjk_name), 'artist_href': self._uri_path}

    def find_associated(self, name, min_score=75, include_score=False):
        match_fmt = '{}: {} matched {} {!r} with score={} because its alias={!r} =~= {!r}'
        best_score, best_alias, best_val, best_type, best_entity = 0, None, None, None, None
        for etype in ('member', 'sub_unit', 'associated_act'):
            log.debug('Processing {}\'s {}s'.format(self, etype))
            try:
                egroup = getattr(self, etype + 's')
            except AttributeError as e:
                log.debug('{}: Error getting attr \'{}s\': {}\n{}'.format(self, etype, e, traceback.format_exc()))
                continue
            for entity in egroup:
                score, alias, val = entity.score_match(name)
                if score >= 100:
                    # log.debug(match_fmt.format(self, entity, etype, name, score, alias, val), extra={'color': 100})
                    return (score, entity) if include_score else entity
                elif score > best_score:
                    best_score, best_alias, best_val, best_type, best_entity = score, alias, val, etype, entity

            if best_score > min_score:
                msg = match_fmt.format(self, best_entity, best_type, name, best_score, best_alias, best_val)
                log.debug(msg, extra={'color': 100})
                return (best_score, best_entity) if include_score else best_entity

        fmt = 'Unable to find member/sub-unit/associated act of {} named {!r}'
        raise MemberDiscoveryException(fmt.format(self, name))


class WikiGroup(WikiArtist):
    _category = 'group'

    def __init__(self, uri_path=None, client=None, **kwargs):
        super().__init__(uri_path, client, **kwargs)
        self.subunit_of = None
        if self._raw and not kwargs.get('no_init'):
            clean_soup = self._clean_soup
            if re.search('^.* is (?:a|the) .*?sub-?unit of .*?group', clean_soup.text.strip()):
                for i, a in enumerate(clean_soup.find_all('a')):
                    href = a.get('href') or ""
                    href = href[6:] if href.startswith('/wiki/') else href
                    if href and (href != self._uri_path):
                        self.subunit_of = WikiGroup(href)
                        break

    def _members(self):
        if not self._raw:
            return
        elif isinstance(self._client, KpopWikiClient):
            yield from find_group_members(self, self._clean_soup)
        elif isinstance(self._client, WikipediaClient):
            yield from parse_wikipedia_group_members(self, self._clean_soup)
        else:
            log.warning('{}: No group member parsing has been configured for {}'.format(self, self.url))

    @cached_property
    def members(self):
        members = []
        for href, member_name in self._members():
            log.debug('{}: Looking up member href={!r} name={!r}'.format(self, href, member_name))
            if member_name:
                name = member_name if isinstance(member_name, str) else member_name[0]
            else:
                name = None
            if name and self._has_no_valid_links(href, name):
                fmt = '{}: Skipping page search for member={!r} found on {} because it has a red link'
                log.debug(fmt.format(self, member_name, self.url), extra={'color': 94})
                members.append(WikiSinger(None, name=member_name, no_fetch=True, _member_of=self))
            elif href:
                members.append(WikiSinger(href, _member_of=self))
            else:
                members.append(WikiSinger(None, name=member_name, no_fetch=True, _member_of=self))
        return members

    @cached_property
    def sub_units(self):
        su_ele = self._clean_soup.find(id=re.compile('sub[-_]?units', re.IGNORECASE))
        if not su_ele:
            return []

        while su_ele and not su_ele.name.startswith('h'):
            su_ele = su_ele.parent
        ul = su_ele.next_sibling.next_sibling
        if not ul or ul.name != 'ul':
            raise RuntimeError('Unexpected sibling element for sub-units')

        sub_units = []
        for li in ul.find_all('li'):
            a = li.find('a')
            href = a.get('href') if a else None
            if href:
                sub_units.append(WikiGroup(href[6:] if href.startswith('/wiki/') else href))
        return sub_units


class WikiSinger(WikiArtist):
    _category = 'singer'
    _member_rx = re.compile(
        r'^.* is (?:a|the) (.*?)(?:member|vocalist|rapper|dancer|leader|visual|maknae) of .*?group (.*)\.'
    )

    def __init__(self, uri_path=None, client=None, *, _member_of=None, **kwargs):
        super().__init__(uri_path, client, **kwargs)
        self.member_of = _member_of
        if self._raw:
            clean_soup = self._clean_soup
            mem_match = self._member_rx.search(clean_soup.text.strip())
            if mem_match:
                if 'former' not in mem_match.group(1):
                    group_name = mem_match.group(2)
                    m = re.match(r'^(.*)\.\s+[A-Z]', group_name)
                    if m:
                        group_name = m.group(1)
                    # log.debug('{} appears to be a member of group {!r}; looking for group page...'.format(self, group_name))
                    for i, a in enumerate(clean_soup.find_all('a')):
                        if a.text and a.text in group_name:
                            href = (a.get('href') or "")[6:]
                            # log.debug('{}: May have found group match for {!r} => {!r}, href={!r}'.format(self, group_name, a.text, href))
                            if href and (href != self._uri_path):
                                try:
                                    self.member_of = WikiGroup(href)
                                except WikiTypeError as e:
                                    fmt = '{}: Found possible group match for {!r}=>{!r}, href={!r}, but {}'
                                    log.debug(fmt.format(self, group_name, a.text, href, e))
                                else:
                                    break
            else:
                for associated in self.associated_acts:
                    if isinstance(associated, WikiGroup):
                        for href, member_name in associated._members():
                            if self._uri_path == href:
                                self.member_of = associated
                                break

            eng_first, eng_last, cjk_eng_first, cjk_eng_last = None, None, None, None
            birth_names = self._side_info.get('birth_name', [])
            if not birth_names:
                birth_names = [(self._side_info.get('birth name'), self._side_info.get('native name'))]
                if not self.cjk_name:
                    if birth_names[0][1] and LangCat.categorize(birth_names[0][1]) in LangCat.asian_cats:
                        self.cjk_name = birth_names[0][1]
                        self.name = multi_lang_name(self.english_name, self.cjk_name)

            for eng, cjk in birth_names:
                if eng and cjk:
                    cjk_eng_last, cjk_eng_first = eng.split(maxsplit=1)
                    self._add_aliases((eng, cjk))
                elif eng:
                    eng_first, eng_last = eng.rsplit(maxsplit=1)
                    self._add_aliases((eng, eng_first))
                    self.__add_aliases(eng_first)
                elif cjk:
                    self._add_alias(cjk)

            if cjk_eng_first or cjk_eng_last:
                if eng_last:
                    eng_first = cjk_eng_first if eng_last == cjk_eng_last else cjk_eng_last
                    self._add_alias(eng_first)
                    self.__add_aliases(eng_first)
                else:
                    self._add_alias(cjk_eng_first)

            if self.english_name:
                self.__add_aliases(self.english_name)

    def __add_aliases(self, name):
        for c in ' -':
            if c in name:
                name_split = name.split(c)
                for k in ('', ' ', '-'):
                    joined = k.join(name_split)
                    if joined not in self.aliases:
                        self._add_alias(joined)

    @cached_property
    def birthday(self):
        if isinstance(self._client, DramaWikiClient):
            return self._profile.get('birthdate')
        return self._side_info.get('birth_date')

    def matches(self, other, *args, **kwargs):
        is_name_match = super().matches(other, *args, **kwargs)
        if is_name_match and isinstance(other, WikiSinger) and self.birthday and other.birthday:
            return self.birthday == other.birthday
        return is_name_match

    @cached_property
    def qualname(self):
        """Like an FQDN for artists - if this is a WikiSinger, include the group they are a member of"""
        try:
            member_of = self.member_of
        except AttributeError:
            pass
        else:
            if member_of:
                return '{} [{}]'.format(self.name, member_of.name)
        return self.name

    def _as_collab(self):
        collab_dict = {'artist': (self.english_name, self.cjk_name), 'artist_href': self._uri_path}
        try:
            group = self.member_of
        except AttributeError:
            pass
        else:
            if group:
                collab_dict.update(of_group=(group.english_name, group.cjk_name), group_href=group._uri_path)
        return collab_dict


class WikiSongCollection(WikiEntity):
    _category = ('album', 'soundtrack', 'collab/feature/single')
    _part_rx = re.compile(r'(?:part|code no)\.?\s*', re.IGNORECASE)
    _bonus_rx = re.compile(r'^(.*)\s+bonus tracks?$', re.IGNORECASE)

    def __init__(
        self, uri_path=None, client=None, *, disco_entry=None, album_info=None, artist_context=None,
        version_title=None, **kwargs
    ):
        super().__init__(uri_path, client, **kwargs)
        self._track_cache = {}
        self._discography_entry = disco_entry or {}
        self.english_name, self.cjk_name, self.stylized_name, self.aka, self._info = None, None, None, None, None
        self._album_info = album_info or {}
        self._albums = []
        self._primary_artist = None
        self._intended = None
        self._artist_context = artist_context
        self._track_lists = None
        if isinstance(self._client, DramaWikiClient) or kwargs.get('no_init'):
            return
        elif self._raw:
            self._albums = albums = self._client.parse_album_page(self._uri_path, self._clean_soup, self._side_info)
            artists = albums[0]['artists']
            try:
                artists_hrefs = list(filter(None, (a.get('artist_href') for a in artists)))
                artists_names = list(filter(None, (a.get('artist')[0] for a in artists)))
            except AttributeError as e:
                log.error('Error processing artists for {}: {}'.format(self.url, artists))
                raise e

            if len(albums) > 1:
                err_base = '{} contains both original+repackaged album info on the same page'.format(uri_path)
                if not (disco_entry or version_title):
                    msg = '{} - a discography entry is required to identify it'.format(err_base)
                    raise WikiEntityIdentificationException(msg)

                disco_entry = disco_entry or {}
                d_title = disco_entry.get('title') or version_title
                d_lc_title = d_title.lower()
                try:
                    d_artist_name, d_artist_uri_path = disco_entry.get('primary_artist')    # tuple(name, uri_path)
                except TypeError as e:
                    d_artist_name, d_artist_uri_path = None, None
                    d_no_artist = True
                else:
                    d_no_artist = False
                d_lc_artist = d_artist_name.lower() if d_artist_name else ''

                if d_no_artist or d_artist_uri_path in artists_hrefs or d_lc_artist in map(str.lower, artists_names):
                    for album in albums:
                        if d_lc_title in map(str.lower, map(str, album['title_parts'])):
                            self._album_info = album
                else:               # Likely linked as a collaboration
                    for package in self.packages:
                        for edition, disk, tracks in package.editions_and_disks:
                            for track in tracks:
                                track_name = track.long_name.lower()
                                if d_lc_title in track_name and d_lc_artist in track_name:
                                    fmt = 'Matched {!r} - {!r} to {} as a collaboration'
                                    log.debug(fmt.format(d_artist_name, d_title, package))
                                    self._album_info = package._album_info
                                    self._intended = edition, disk, track

                if not self._album_info:
                    msg = '{}, and it could not be matched with discography entry: {}'.format(err_base, disco_entry)
                    raise WikiEntityIdentificationException(msg)
            else:
                self._album_info = albums[0]

            self.english_name, self.cjk_name, self.stylized_name, self.aka, self._info = self._album_info['title_parts']
        elif disco_entry:
            self._primary_artist = disco_entry.get('primary_artist')
            if 'title_parts' in disco_entry:
                self.english_name, self.cjk_name, self.stylized_name, self.aka, self._info = disco_entry['title_parts']
            else:
                try:
                    try:
                        self.english_name, self.cjk_name = eng_cjk_sort(disco_entry['title'])
                    except ValueError as e1:
                        fmt = 'Unexpected disco_entry title for {}: {!r}; retrying'
                        log.debug(fmt.format(self.url, disco_entry['title']))
                        self.english_name, self.cjk_name = split_name(disco_entry['title'], allow_cjk_mix=True)
                except Exception as e:
                    if not kwargs.get('no_fetch'):
                        log.error('Error processing disco entry title: {}'.format(e))
                    msg = 'Unable to find valid title in discography entry: {}'.format(disco_entry)
                    raise WikiEntityInitException(msg) from e
        else:
            msg = 'A valid uri_path / discography entry are required to initialize a {}'.format(type(self).__name__)
            raise WikiEntityInitException(msg)

        self._track_lists = self._album_info.get('track_lists')
        if self._track_lists is None:
            album_tracks = self._album_info.get('tracks')
            if album_tracks:
                self._track_lists = [album_tracks]

        if not self.cjk_name and self._track_lists:
            for track_list in self._track_lists:
                for track in track_list.get('tracks', []):
                    try:
                        eng, cjk = track.get('name_parts')
                    except Exception as e:
                        pass
                    else:
                        if eng == self.english_name:
                            self.cjk_name = cjk
                            break

        self.name = multi_lang_name(self.english_name, self.cjk_name)
        if self._info:
            self.name = ' '.join(chain((self.name,), map('({})'.format, self._info)))

        if self._raw and isinstance(self._client, KpopWikiClient) and not disco_entry and not artist_context:
            artist = None
            try:
                # log.debug('{}: {} Trying to access artist...'.format(self, self.url))
                artist = self.artist
            except AttributeError:
                try:
                    artist = self.artists[0]
                except IndexError:
                    pass
            finally:
                for key in ('artists', '_artists', 'artist'):
                    try:
                        del self.__dict__[key]
                    except KeyError:
                        pass

            if artist is not None:
                for album in artist.discography:
                    if album == self:
                        self._discography_entry = album._discography_entry
                        break

    def __lt__(self, other):
        comparison_type_check(self, other, WikiSongCollection, '<')
        return self.name < other.name

    def __gt__(self, other):
        comparison_type_check(self, other, WikiSongCollection, '>')
        return self.name > other.name

    def _additional_aliases(self):
        try:
            artist = self._artist_context or self.artist
        except Exception:
            pass
        else:
            return ['{} {}'.format(artist.english_name, a) for a in self._aliases()]

    @cached_property
    def language(self):
        return self._discography_entry.get('language')

    @cached_property
    def released(self):
        return self._album_info.get('released')

    @cached_property
    def year(self):
        return self._discography_entry.get('year')

    @cached_property
    def album_type(self):
        base_type = self._discography_entry.get('base_type')
        if isinstance(self._client, WikipediaClient):
            sub_type = self._discography_entry.get('sub_type')
            if base_type == 'albums':
                if sub_type == 'reissues':
                    base_type = 'repackage_albums'
                elif sub_type == 'compilation albums':
                    base_type = 'best_albums'
                else:
                    base_type = sub_type.replace(' ', '_')

        try:
            return DISCOGRAPHY_TYPE_MAP[base_type]
        except KeyError as e0:
            if base_type is not None:
                try:
                    return DISCOGRAPHY_TYPE_MAP[base_type.replace(' ', '_')]
                except KeyError as e:
                    raise MusicWikiException('{}: Unexpected album base_type: {!r}'.format(self, base_type)) from e
            else:
                return None

    @cached_property
    def album_num(self):
        return self._discography_entry.get('num')

    @cached_property
    def num_and_type(self):
        lang = self._discography_entry.get('language')
        if lang and lang.lower() != 'korean':
            return '{} {} {}'.format(self.album_num, lang.title(), self.album_type)
        return '{} {}'.format(self.album_num, self.album_type)

    @cached_property
    def title(self):
        extra = ' '.join(map('({})'.format, self._info)) if self._info else ''
        return '{} {}'.format(self.name, extra) if extra else self.name

    @cached()
    def expected_rel_dir(self):
        numbered_type = self.album_type in ALBUM_NUMBERED_TYPES
        if numbered_type or self.album_type in ('Single', ):
            try:
                release_date = '[{}] '.format(self._album_info['released'].strftime('%Y.%m.%d'))
            except KeyError:
                release_date = ''

            if numbered_type:
                title = '{}{} [{}]'.format(release_date, self.title, self.num_and_type)
            else:
                title = '{}{}'.format(release_date, self.title)
        else:
            title = self.title

        return Path(self.album_type + 's').joinpath(sanitize_path(title)).as_posix()

    @cached()
    def expected_rel_path(self):
        return self.artist.expected_rel_path().joinpath(self.expected_rel_dir())

    @cached_property
    def _artists(self):
        if self._primary_artist:
            artists = {tuple(sorted(
                {'artist': eng_cjk_sort(self._primary_artist[0]), 'artist_href': self._primary_artist[1]}.items()
            ))}
        else:
            artists = set()

        d_collabs = self._discography_entry.get('collaborators', [])
        a_artists = self._album_info.get('artists', [])
        for artist in chain(a_artists, d_collabs):
            try:
                artists.add(tuple(sorted(artist.items())))
            except Exception as e:
                log.error('Error processing artists for {}'.format(self))
                raise e

        artists = [dict(artist) for artist in artists]
        artist_map = {}
        for artist in artists:
            artist_name = artist['artist']
            if artist_name in artist_map:
                current = artist_map[artist_name]
                for key, val in artist.items():
                    if current.get(key) is None and val is not None:
                        current[key] = val
            else:
                artist_map[artist_name] = artist
        return list(artist_map.values())

    @cached_property
    def artists(self):
        artists = set()
        for artist in self._artists:
            # log.debug('{}: Processing artist: {}'.format(self, artist))
            name = artist['artist']
            if name[0].lower() in ('various artists', 'various'):
                continue

            href = artist.get('artist_href')
            of_group = artist.get('of_group')
            # group_href = artist.get('group_href')
            if self._has_no_valid_links(href, name[0]):
                fmt = '{}: Skipping page search for artist={!r} of_group={!r} found on {} because it has a red link'
                log.debug(fmt.format(self, name, of_group, self.url), extra={'color': 94})
                artists.add(WikiArtist(href, name=name, of_group=of_group, client=self._client, no_fetch=True))
                continue

            try:
                # log.debug('{}: Looking for artist href={!r} name={!r} of_group={!r}'.format(self, href, name, of_group))
                artist = WikiArtist(href, name=name, of_group=of_group, client=self._client)
            except AmbiguousEntityException as e:
                # log.debug('{}: artist={} => ambiguous'.format(self, artist))
                if self._artist_context and isinstance(self._artist_context, WikiGroup):
                    found = False
                    for member in self._artist_context.members:
                        if member._uri_path in e.alternatives:
                            artists.add(member)
                            found = True
                            break
                    if found:
                        continue

                fmt = '{}\'s artist={!r} is ambiguous'
                no_warn = False
                if e.alternatives:
                    fmt += ' - it could be one of: {}'.format(' | '.join(e.alternatives))
                    if len(e.alternatives) == 1:
                        alt_href = e.alternatives[0]
                        try:
                            alt_entity = WikiEntity(alt_href)
                        except Exception:
                            pass
                        else:
                            if not isinstance(alt_entity, WikiArtist):
                                fmt = '{}\'s artist={!r} has no page in {}; the disambiguation alternative was {}'
                                log.debug(fmt.format(self, name, alt_entity._client.host, alt_entity))
                                no_warn = True

                if not no_warn:
                    log.log(19, fmt.format(self, name), extra={'color': (11, 9)})

                artists.add(WikiArtist(href, name=name, no_fetch=True, client=self._client))
            except CodeBasedRestException as e:
                # log.debug('{}: artist={} => {}'.format(self, artist, e))
                if isinstance(self._client, KpopWikiClient):
                    try:
                        artist = WikiArtist(href, name=name, of_group=of_group)
                    except CodeBasedRestException as e2:
                        fmt = 'Error retrieving info for {}\'s artist={!r} (href={!r}) from multiple clients: {}'
                        log.debug(fmt.format(self, name, href, e), extra={'color': 13})
                        artists.add(WikiArtist(href, name=name, no_fetch=True))
                    else:
                        artists.add(artist)
                else:
                    msg = 'Error retrieving info for {}\'s artist={!r} (href={!r}): {}'.format(self, name, href, e)
                    if href is None:
                        log.log(9 if isinstance(self, WikiSoundtrack) else 10, msg)
                    else:
                        log.error(msg, extra={'color': 13})
                    artists.add(WikiArtist(href, name=name, no_fetch=True))
            except WikiTypeError as e:
                # log.debug('{}: artist={} => {}'.format(self, artist, e))
                log_lvl = logging.DEBUG if isinstance(self._client, WikipediaClient) else logging.WARNING
                if e.category == 'disambiguation':
                    fmt = '{}\'s artist={!r} has an ambiguous href={}'
                    log.log(log_lvl, fmt.format(self, name, e.url), extra={'color': (11, 9)})
                else:
                    fmt = '{}\'s artist={!r} doesn\'t appear to be an artist: {}'
                    log.log(log_lvl, fmt.format(self, name, e), extra={'color': (11, 9)})
                    # raise e
                artists.add(WikiArtist(href, name=name, no_fetch=True))
            except Exception as e:
                fmt = '{}: Unable to find artist href={!r} name={!r} of_group={!r} found on {}: {}'
                log.error(fmt.format(self, href, name, of_group, self.url, e), extra={'color': 9})
                artists.add(WikiArtist(href, name=name, no_fetch=True))
            else:
                # log.debug('{}: artist={} => adding'.format(self, artist))
                artists.add(artist)
        return sorted(artists)

    @cached_property
    def artist(self):
        artists = self.artists
        if len(artists) == 1:
            return artists[0]
        elif self._artist_context:
            return self._artist_context

        if self._raw:
            artists_raw = self._side_info.get('artist')
            if artists_raw and len(artists_raw) == 1:
                lc_artist_raw = artists_raw[0].lower()
                feat_indicators = ('feat. ', 'featuring ', 'with ')
                kw_idx = next((lc_artist_raw.index(val) for val in feat_indicators if val in lc_artist_raw), None)
                if kw_idx is not None:
                    before = artists_raw[0][:kw_idx].strip()
                    log.debug('{}: Trying to find primary artist from side info: {!r}'.format(self, before))
                    primary = {artist for artist in artists if artist.matches(before)}
                    if len(primary) == 1:
                        return primary.pop()
                    else:
                        fmt = '{}: Unable to determine primary artist based on side info - pre-feat matches: {}'
                        log.debug(fmt.format(self, primary))

        raise AttributeError('{} has multiple contributing artists and no artist context'.format(self))

    @cached_property
    def collaborators(self):
        artists = self.artists
        try:
            primary = self.artist
        except AttributeError:
            primary = None

        if len(artists) < 2:
            return []
        elif primary:
            return [artist for artist in artists if artist != primary]
        else:
            return artists

    @cached_property
    def _editions_by_disk(self):
        editions_by_disk = defaultdict(list)
        for track_section in self._track_lists:
            editions_by_disk[track_section.get('disk')].append(track_section)
        return editions_by_disk

    def _get_tracks(self, edition_or_part=None, disk=None):
        if self._track_lists:
            # log.debug('{}: Retrieving tracks for edition_or_part={!r}'.format(self, edition_or_part))
            if disk is None and edition_or_part is None or isinstance(edition_or_part, int):
                edition_or_part = edition_or_part or 0
                try:
                    return self._track_lists[edition_or_part]
                except IndexError as e:
                    msg = '{} has no part/edition called {!r}'.format(self, edition_or_part)
                    raise InvalidTrackListException(msg) from e

            editions = self._editions_by_disk[disk or 1]
            if not editions and disk is None:
                editions = self._editions_by_disk[disk]
            if not editions:
                raise InvalidTrackListException('{} has no disk {}'.format(self, disk))
            elif edition_or_part is None:
                return editions[0]

            # noinspection PyUnresolvedReferences
            lc_ed_or_part = edition_or_part.lower()
            is_part = lc_ed_or_part.startswith(('part', 'code no'))
            if is_part:
                lc_ed_or_part = self._part_rx.sub('part ', lc_ed_or_part)

            bonus_match = None
            for i, edition in enumerate(editions):
                section = edition.get('section') or ''
                if section and not isinstance(section, str):
                    section = section[0]
                name = section.lower()
                if name == lc_ed_or_part or (is_part and lc_ed_or_part in self._part_rx.sub('part ', name)):
                    return edition
                else:
                    m = self._bonus_rx.match(name)
                    if m and m.group(1).strip() == lc_ed_or_part:
                        bonus_match = i
                        # log.debug('bonus_match={}: {}'.format(bonus_match, edition))
                        break

            if bonus_match is not None:
                edition = editions[bonus_match]
                first_track = min(t['num'] for t in edition['tracks'])
                if first_track == 1:
                    return edition
                name = self._bonus_rx.match(edition['section']).group(1).strip()
                combined = {
                    'section': name, 'tracks': edition['tracks'].copy(), 'disk': edition.get('disk'),
                    'links': edition.get('links', [])
                }

                combos = edition_combinations(editions[:bonus_match], first_track)
                # log.debug('Found {} combos'.format(len(combos)))
                if len(combos) != 1:
                    # for combo in combos:
                    #     tracks = sorted(t['num'] for t in chain.from_iterable(edition['tracks'] for edition in combo))
                    #     log.debug('Combo: {} => {}'.format(', '.join(repr(e['section']) for e in combo), tracks))
                    raise InvalidTrackListException('{}: Unable to reconstruct {!r}'.format(self, name))

                for edition in combos[0]:
                    combined['tracks'].extend(edition['tracks'])
                    combined['links'].extend(edition.get('links', []))

                combined['tracks'] = sorted(combined['tracks'], key=lambda t: t['num'])
                combined['links'] = sorted(set(combined['links']))
                return combined
            raise InvalidTrackListException('{} has no part/edition called {!r}'.format(self, edition_or_part))
        else:
            if 'single' in self.album_type.lower():
                return {'tracks': [{'name_parts': (self.english_name, self.cjk_name)}]}
            else:
                fmt = '{}: No page content found for {} - returning empty track list'
                log.log(9, fmt.format(self._client.host, self), extra={'color': 8})
                return {'tracks': []}

    @cached('_track_cache', exc=True)
    def get_tracks(self, edition_or_part=None, disk=None):
        # log.debug('{}.get_tracks({!r}, {!r}) called'.format(self, edition_or_part, disk), extra={'color': 76})
        if self._intended is not None and edition_or_part is None and disk is None:
            if len(self._intended) == 3:
                return [WikiTrack(self._intended[2]._info, self, self._artist_context)]
            elif len(self._intended) == 2:
                # noinspection PyTupleAssignmentBalance
                edition_or_part, disk = self._intended
        _tracks = self._get_tracks(edition_or_part, disk)
        return [WikiTrack(info, self, self._artist_context) for info in _tracks['tracks']]

    @cached_property
    def editions_and_disks(self):
        bonus_rx = re.compile('^(.*)\s+bonus tracks?$', re.IGNORECASE)
        editions = []
        for edition in self._track_lists:
            section = edition.get('section')
            if section and not isinstance(section, str):
                section = section[0]
            try:
                m = bonus_rx.match(section or "")
            except TypeError as e:
                log.error('{}: Unexpected section value in {}: {}'.format(self, self.url, section))
                raise e
            name = m.group(1).strip() if m else section
            disk = edition.get('disk')
            editions.append((name, disk, self.get_tracks(name, disk)))
        return editions

    @cached_property
    def packages(self):
        if len(self._albums) == 1:
            return [self]
        elif len(self._artists) > 1:
            fmt = 'Packages can only be retrieved for {} objects with 1 packaging or a primary artist'
            fmt += '; {}\'s artists: {}'
            raise AttributeError(fmt.format(type(self).__name__, self, self._artists))

        try:
            artist = self._artists[0]['artist']
        except Exception as e:
            log.error('Unable to get artist from {} / {}'.format(self, self._artists))
            raise e

        packages = []
        for album in self._albums:
            disco_entry = {'title': album['title_parts'][0], 'artist': artist}
            tmp = WikiSongCollection(self._uri_path, self._client, disco_entry=disco_entry)
            packages.append(tmp)
        return packages

    def find_track(self, name, min_score=75, include_score=False, **kwargs):
        match_fmt = '{}: {} matched {!r} with score={} because its alias={!r} =~= {!r}'
        best_score, best_alias, best_val, best_track = 0, None, None, None
        normalized = WikiTrack._normalize_for_matching(name)
        for track in self.get_tracks():
            score, alias, val = track.score_match(normalized, normalize=False, **kwargs)
            if score >= 100:
                # log.debug(match_fmt.format(self, track, name, score, alias, val))
                return (track, score) if include_score else track
            elif score > best_score:
                best_score, best_alias, best_val, best_track = score, alias, val, track

        if best_score > min_score:
            if best_score < 95:
                log.debug(match_fmt.format(self, best_track, name, best_score, best_alias, best_val))
            return (best_track, best_score) if include_score else best_track
        return (None, -1) if include_score else None

    def score_match(self, other, *args, **kwargs):
        if isinstance(other, str):
            rom_num = next((rn for rn in ROMAN_NUMERALS if other.endswith(' ' + rn)), None)
            if rom_num is not None:
                alt_other = re.sub(r'\s+{}$'.format(rom_num), ' {}'.format(ROMAN_NUMERALS[rom_num]), other)
                other = (other, alt_other)
        return super().score_match(other, *args, **kwargs)


class WikiAlbum(WikiSongCollection):
    _category = 'album'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        repackage_title = self._album_info.get('repackage_of_title')
        if self.name == repackage_title:
            self.name += ' (Repackage)'
            self.english_name += ' (Repackage)'

    def _aliases(self):
        aliases = super()._aliases()
        if self.repackage_of:
            for alias in list(aliases):
                if 'repackage' not in alias.lower():
                    aliases.add('{} (Repackage)'.format(alias))
        return aliases

    @cached_property
    def num_and_type(self):
        base = super().num_and_type
        return '{} Repackage'.format(base) if self.repackage_of else base

    @cached_property
    def repackaged_version(self):
        title = self._album_info.get('repackage_title')
        href = self._album_info.get('repackage_href')
        if href:
            return WikiAlbum(href, client=self._client, version_title=title)
        return None

    @cached_property
    def repackage_of(self):
        title = self._album_info.get('repackage_of_title')
        href = self._album_info.get('repackage_of_href')
        if href:
            return WikiAlbum(href, client=self._client, version_title=title)
        return None


class WikiSoundtrack(WikiSongCollection):
    _category = 'soundtrack'
    _ost_name_rx = re.compile(r'^(.* OST)\s*-?\s*((?:part|code no)\.?\s*\d+)$', re.IGNORECASE)
    _ost_name_paren_rx = re.compile(r'^(.*) \(.*\) OST$', re.IGNORECASE)
    _ost_simple_rx = re.compile(r'^(.* OST)', re.IGNORECASE)

    def __init__(self, uri_path=None, client=None, **kwargs):
        super().__init__(uri_path, client, **kwargs)
        if isinstance(self._client, DramaWikiClient):
            if not self._raw:
                raise WikiEntityInitException('WikiSoundtrack requires a valid uri_path')
            self._track_lists = parse_ost_page(self._uri_path, self._clean_soup, client)
            self._album_info = {
                'track_lists': self._track_lists, 'num': None, 'type': 'OST', 'repackage': False, 'length': None,
                'released': None, 'links': []
            }
            part_1 = self._track_lists[0]
            eng, cjk = part_1['info']['title']

            try:
                eng, cjk = (self._ost_name_rx.match(val).group(1).strip() for val in (eng, cjk))
            except Exception as e:
                try:
                    eng, cjk = (self._ost_simple_rx.match(val).group(1).strip() for val in (eng, cjk))
                except Exception as e1:
                    log.debug('OST @ {!r} had unexpected name: {!r} / {!r}'.format(self._uri_path, eng, cjk))
                # raise WikiEntityInitException('Unexpected OST name for {}'.format(self._uri_path)) from e
            self.english_name, self.cjk_name = eng, cjk
            self.name = multi_lang_name(self.english_name, self.cjk_name)
            try:
                tv_series = self.tv_series
            except AttributeError:
                pass
            else:
                self._add_aliases(('{} OST'.format(a) for a in tv_series.aliases))

        if self._discography_entry:
            m = self._ost_name_rx.match(self._discography_entry.get('title', ''))
            if m:
                self._intended = m.group(2).strip(), None
                if not isinstance(self._client, DramaWikiClient):
                    title = m.group(1).strip()
                    try:
                        self.english_name, self.cjk_name = eng_cjk_sort(title)
                    except ValueError as e1:
                        log.debug('Unexpected disco_entry title for {}: {!r}; retrying'.format(self, title))
                        self.english_name, self.cjk_name = split_name(title)
                    self.name = multi_lang_name(self.english_name, self.cjk_name)

    def _additional_aliases(self):
        return chain(super()._additional_aliases(), [e[0] for e in self.editions_and_disks])

    def score_match(self, other, *args, **kwargs):
        if isinstance(other, str):
            m1 = self._ost_name_rx.match(other)
            if m1:
                title1 = m1.group(1)
                if title1.endswith(' -'):
                    title1 = title1[:-1].strip()

                m2 = self._ost_name_paren_rx.match(title1)
                if m2:
                    title2 = '{} OST'.format(m2.group(1).strip())
                    other = (other, title1, title2)
                else:
                    other = (other, title1)
        # log.debug('{}: Comparing to: {}'.format(self, other))
        return super().score_match(other, *args, **kwargs)

    @cached_property
    def tv_series(self):
        if not isinstance(self._client, DramaWikiClient):
            raise AttributeError('{} has no attribute tv_series'.format(self))

        li = self._clean_soup.find(lambda tag: tag.name == 'li' and tag.text.startswith('Title:'))
        if li:
            a = li.find('a')
            if a:
                href = a.get('href')
                if href:
                    return WikiTVSeries(href, client=self._client)
        raise AttributeError('{} has no attribute tv_series'.format(self))

    @cached_property
    def _artists(self):
        if not isinstance(self._client, DramaWikiClient):
            return super()._artists

        artists = defaultdict(dict)
        keys = ('eng', 'cjk', 'group_eng', 'group_cjk', 'artist_href', 'group_href')
        for track_section in self._track_lists:
            for _artist in track_section['info']['artist']:
                eng, cjk = _artist['artist']
                artist_href = _artist.get('artist_href')
                group_href = _artist.get('group_href')
                try:
                    group_eng, group_cjk = _artist['of_group']
                except KeyError:
                    group_eng, group_cjk = None, None

                # log.debug('Processing artist: {}'.format(', '.join('{}={!r}'.format(k, v) for k, v in zip(keys, (eng, cjk, group_eng, group_cjk, artist_href, group_href)))))
                for key, val in zip(keys, (eng, cjk, group_eng, group_cjk, artist_href, group_href)):
                    if val:
                        artists[eng].setdefault(key, val)
        return list(artists.values())

    @cached_property
    def artists(self):
        if not isinstance(self._client, DramaWikiClient):
            return super().artists

        artists = set()
        for _artist in self._artists:
            eng, cjk = _artist['eng'], _artist.get('cjk')
            if eng.lower() == 'various artists':
                continue

            group_eng = _artist.get('group_eng')
            try:
                try:
                    artist = WikiArtist(aliases=(eng, cjk), of_group=group_eng)
                except WikiTypeError as e:
                    if group_eng:
                        artist = WikiArtist(aliases=(eng, cjk))
                    else:
                        raise e
            except AmbiguousEntityException as e:
                d_artist_href = _artist.get('artist_href')
                if d_artist_href:
                    d_artist = WikiArtist(d_artist_href, client=self._client)
                    if e.alternatives:
                        alternatives = []
                        _alts = list(e.alternatives)
                        for alt_href in e.alternatives:
                            if 'singer' in alt_href:
                                _alts.remove(alt_href)
                                alternatives.append(alt_href)
                        alternatives.extend(_alts)
                    else:
                        alternatives = e.alternatives

                    for i, alt_href in enumerate(alternatives):
                        if i > 3:
                            fmt = '{}: Skipping alt href comparison for {} =?= {} because it has too many alternatives'
                            log.warning(fmt.format(self, d_artist, alt_href))
                        else:
                            client = WikiClient.for_site(e.site) if e.site else None
                            tmp_artist = WikiArtist(alt_href, client=client)
                            if tmp_artist.matches(d_artist):
                                log.debug('{}: Matched {} to {}'.format(self, d_artist, tmp_artist))
                                artists.add(tmp_artist)
                                break
                            else:
                                log.debug('{}: {} != {}'.format(self, d_artist, tmp_artist))
                    else:
                        fmt = '{}\'s artist={!r} is ambiguous'
                        if e.alternatives:
                            fmt += ' - it could be one of: {}'.format(' | '.join(e.alternatives))
                        log.log(19, fmt.format(self, eng, group_eng), extra={'color': (11, 9)})
                        artists.add(WikiArtist(name=eng, no_fetch=True))
                else:
                    fmt = '{}\'s artist={!r} is ambiguous'
                    if e.alternatives:
                        fmt += ' - it could be one of: {}'.format(' | '.join(e.alternatives))
                    log.warning(fmt.format(self, eng), extra={'color': (11, 9)})
                    artists.add(WikiArtist(name=eng, no_fetch=True))
            except CodeBasedRestException as e:
                if e.code == 404:
                    log.debug('No page found for {}\'s artist={!r} of_group={!r}'.format(self, eng, group_eng))
                else:
                    fmt = 'Error retrieving info for {}\'s artist={!r} of_group={!r}: {}'
                    log.error(fmt.format(self, eng, group_eng, e), extra={'color': 13})
                artists.add(WikiArtist(name=eng, no_fetch=True))
            except Exception as e:
                fmt = 'Unexpected error processing {}\'s artist={!r} of_group={!r}: {}\n{}'
                log.error(fmt.format(self, eng, group_eng, e, traceback.format_exc()), extra={'color': (11, 9)})
            else:
                artists.add(artist)
        return sorted(artists)

    def _get_tracks(self, edition_or_part=None, disk=None):
        track_info = self._discography_entry.get('track_info')
        use_discography_info = self._intended is None and track_info
        if not use_discography_info and self._raw and self._track_lists:
            log.log(1, 'Skipping WikiSoundtrack _get_tracks({!r}, {!r}) for {}'.format(edition_or_part, disk, self.url))
            return super()._get_tracks(edition_or_part, disk)

        if track_info:
            _tracks = (track_info,) if isinstance(track_info, dict) else track_info
            tracks = []
            for _track in _tracks:
                track = _track.copy()
                track['collaborators'] = strify_collabs(track.get('collaborators') or [])
                misc = track.get('misc') or []
                if self._info:
                    misc.extend(self._info)
                track['misc'] = misc
                track['from_discography_info'] = True
                tracks.append(track)

            return {'tracks': tracks}
        else:
            fmt = '{}: No page content found for {} - returning empty track list'
            log.log(9, fmt.format(self._client.host, self), extra={'color': 8})
            return {'tracks': []}


class WikiFeatureOrSingle(WikiSongCollection):
    _category = 'collab/feature/single'

    def _get_tracks(self, edition_or_part=None, disk=None):
        if self._raw and self._track_lists and not self._album_info.get('fake_track_list'):
            _tracks = super()._get_tracks(edition_or_part, disk)['tracks']
            tracks = self.__update_tracks(_tracks)
        else:
            track_info = self._discography_entry.get('track_info')
            if track_info and not self._raw:
                log.debug('{}: Using discography track info'.format(self))
                _tracks = (track_info,) if isinstance(track_info, dict) else track_info
                tracks = self.__update_tracks(_tracks, True)
            else:   # self._raw exists, but it had no track list
                single = None
                if self._track_lists:
                    log.debug('{}: Using album page track info'.format(self))
                    single = self._track_lists[0]['tracks'][0]
                if not single:
                    log.debug('{}: Using side bar track info'.format(self))
                    single = {'name_parts': (self.english_name, self.cjk_name), 'num': 1, 'misc': self._info}
                single['collaborators'] = [a._as_collab() for a in self.collaborators]
                tracks = [single]
        return {'tracks': tracks}

    def __update_tracks(self, _tracks, incl_info=False):
        tracks = []
        album_collabs = [a._as_collab() for a in self.collaborators]
        for _track in _tracks:
            track = _track.copy()
            collabs = album_collabs.copy()
            collabs.extend({'artist': name} for name in (track.get('collaborators') or []))
            track['collaborators'] = collabs
            if incl_info:
                misc = track.get('misc') or []
                if self._info:
                    misc.extend(self._info)
                track['misc'] = misc
            tracks.append(track)
        return tracks


class WikiTrack(WikiMatchable, DictAttrPropertyMixin):
    _category = '__track__'
    __feat_rx = re.compile(r'\((?:with|feat\.?|featuring)\s+(.*?)\)', re.IGNORECASE)
    disk = DictAttrProperty('_info', 'disk', type=int, default=1)
    num = DictAttrProperty('_info', 'num', type=lambda x: x if x is None else int(x), default=None)
    length_str = DictAttrProperty('_info', 'length', default='-1:00')
    language = DictAttrProperty('_info', 'language', default=None)
    version = DictAttrProperty('_info', 'version', default=None)
    misc = DictAttrProperty('_info', 'misc', default=None)
    from_ost = DictAttrProperty('_info', 'from_ost', default=False)
    from_compilation = DictAttrProperty('_info', 'compilation', default=False)
    __collaborators = DictAttrProperty('_info', 'collaborators', default_factory=list)
    _artist = DictAttrProperty('_info', 'artist', default=None)
    _from_disco_info = DictAttrProperty('_info', 'from_discography_info', default=False)

    def __init__(self, info, collection, artist_context):
        self._info = info   # num, length, language, version, name_parts, collaborators, misc, artist
        self._artist_context = artist_context
        self.collection = collection
        self.english_name, self.cjk_name = self._info['name_parts']
        self.name = multi_lang_name(self.english_name, self.cjk_name)
        # fmt = 'WikiTrack: artist_context={}, collection={}, name={}, collabs={}'
        # log.debug(fmt.format(artist_context, collection, self.name, self._info.get('collaborators')))
        self.__processed_collabs = False

    def __process_collabs(self):
        if self.__processed_collabs:
            return
        self.__processed_collabs = True
        if self.from_ost and self._artist_context:
            # log.debug('Comparing collabs={} to aliases={}'.format(self._collaborators, self._artist_context.aliases))
            if not self._from_disco_info:
                if not any(self._artist_context.matches(c['artist']) for c in self._collaborators.values()):
                    # fmt = 'WikiTrack {!r} discarding artist context={}; collabs: {}'
                    # log.debug(fmt.format(self.name, self._artist_context, self._collaborators), extra={'color': 'cyan'})
                    self._artist_context = None
                else:
                    for lc_collab, collab in sorted(self._collaborators.items()):
                        if self._artist_context.matches(collab['artist']):
                            self._collaborators.pop(lc_collab)
        else:
            # Clean up the collaborator list for tracks that include the primary artist in the list of collaborators
            # Example case: LOONA pre-debut single albums
            if self._collaborators:
                if self._artist and self._artist.lower() in self._collaborators:
                    # fmt = 'WikiTrack {!r} discarding artist from collaborators: artist={!r}; collabs: {}'
                    # log.debug(fmt.format(self.name, self._artist, self._collaborators), extra={'color': 'cyan'})
                    self._collaborators.pop(self._artist.lower())
                elif self.collection:
                    try:
                        artist = self.collection.artist
                    except Exception as e:
                        fmt = 'Error processing artist for track {!r} from {}: {}'
                        log.debug(fmt.format(self.name, self.collection, e))
                    else:
                        # fmt = 'WikiTrack {!r} discarding album artist from collaborators: artist={!r}; collabs: {}'
                        # log.debug(fmt.format(self.name, artist, self._collaborators), extra={'color': 'cyan'})
                        for lc_alias in artist.lc_aliases:
                            try:
                                self._collaborators.pop(lc_alias)
                            except KeyError:
                                pass

    @cached_property
    def _repr(self):
        if self.num is not None:
            name = '{}[{:2d}][{!r}]'.format(type(self).__name__, self.num, self.name)
        else:
            name = '{}[??][{!r}]'.format(type(self).__name__, self.name)
        len_str = '[{}]'.format(self.length_str) if self.length_str != '-1:00' else ""
        return '<{}{}>'.format(name, len_str)

    def __repr__(self):
        if self.num is not None:
            name = '{}[{:2d}][{!r}]'.format(type(self).__name__, self.num, self.name)
        else:
            name = '{}[??][{!r}]'.format(type(self).__name__, self.name)
        len_str = '[{}]'.format(self.length_str) if self.length_str != '-1:00' else ""
        return '<{}{}{}>'.format(name, "".join(self._formatted_name_parts), len_str)

    @cached_property
    def _collaborators(self):
        collabs = {}
        addl_collabs = []
        for collab in chain(self.__collaborators, addl_collabs):
            if collab:
                # log.debug('WikiTrack[{!r}]: processing collaborator: {}'.format(self.name, collab))
                if isinstance(collab, dict):
                    eng, cjk = collab['artist']
                    name = eng or cjk
                    collabs[name.lower()] = collab
                elif isinstance(collab, list):
                    addl_collabs.extend(collab)
                else:
                    collabs[collab.lower()] = {'artist': collab}
        return collabs

    @cached_property
    def collaborators(self):
        self.__process_collabs()
        collabs = []
        for collab in self._collaborators.values():
            try:
                artist = WikiArtist(
                    collab.get('artist_href'), aliases=collab['artist'], of_group=collab.get('of_group')
                )
            except Exception as e:
                artist = collab['artist']
                if not isinstance(artist, str):
                    eng, cjk = artist
                    if eng and cjk:
                        artist = '{} ({})'.format(eng, cjk)
                    else:
                        artist = eng or cjk
                of_group = collab.get('of_group')
                if of_group:
                    artist = '{} [{}]'.format(artist, of_group)
            else:
                artist = artist.qualname if collab.get('of_group') else artist.name

            collabs.append(artist)
        return collabs

    @cached_property
    def artist(self):
        if self._artist_context:
            return self._artist_context
        else:
            return self.collection.artist

    @property
    def _cmp_attrs(self):
        return self.collection, self.disk, self.num, self.long_name

    def __lt__(self, other):
        comparison_type_check(self, other, WikiTrack, '<')
        return self._cmp_attrs < other._cmp_attrs

    def __gt__(self, other):
        comparison_type_check(self, other, WikiTrack, '>')
        return self._cmp_attrs > other._cmp_attrs

    @cached_property
    def _formatted_name_parts(self):
        self.__process_collabs()
        parts = []
        if self.version:
            parts.append('{} ver.'.format(self.version) if not self.version.lower().startswith('inst') else self.version)
        if self.language:
            parts.append('{} ver.'.format(self.language))
        if self.misc:
            parts.extend(self.misc)
        if self._artist:
            artist_aliases = set(chain.from_iterable(artist.aliases for artist in self.collection.artists))
            if self._artist not in artist_aliases:
                parts.append('{} solo'.format(self._artist))
        if self._collaborators:
            collabs = ', '.join(self.collaborators)
            if self.from_compilation or (self.from_ost and self._artist_context is None):
                parts.insert(0, 'by {}'.format(collabs))
            else:
                parts.append('Feat. {}'.format(collabs))
        return tuple(map('({})'.format, parts))

    @cached_property
    def long_name(self):
        return ' '.join(chain((self.name,), self._formatted_name_parts))

    def _additional_aliases(self):
        name_end = ' '.join(self._formatted_name_parts)
        aliases = [self.long_name]
        for val in self.english_name, self.cjk_name:
            if val:
                aliases.append('{} {}'.format(val, name_end))
        return aliases

    @property
    def seconds(self):
        m, s = map(int, self.length_str.split(':'))
        return (s + (m * 60)) if m > -1 else 0

    def expected_filename(self, ext='mp3'):
        base = sanitize_path('{}.{}'.format(self.long_name, ext))
        return '{:02d}. {}'.format(self.num, base) if self.num else base

    def expected_rel_path(self, ext='mp3'):
        return self.collection.expected_rel_path().joinpath(self.expected_filename(ext))

    @classmethod
    def _normalize_for_matching(cls, other):
        if isinstance(other, str):
            m = cls.__feat_rx.search(other)
            if m:
                feat = m.group(1)
                if ' of ' in feat:
                    full_feat = feat
                    feat, of_group = feat.split(' of ', 1)
                else:
                    full_feat = None

                if LangCat.contains_any(feat, LangCat.HAN):
                    other_str = other
                    if full_feat:
                        other = {other_str.replace(feat, val) for val in romanized_permutations(feat)}
                        # The replacement of the full text below is intentional
                        other.update(other_str.replace(full_feat, val) for val in romanized_permutations(feat))
                    else:
                        other = {other_str.replace(feat, val) for val in romanized_permutations(feat)}

                    other.add(other_str)
            else:
                lc_other = other.lower()
                if 'japanese ver.' in lc_other and LangCat.contains_any(other, LangCat.JPN):
                    try:
                        parsed = ParentheticalParser().parse(other)
                    except Exception:
                        pass
                    else:
                        for i, part in enumerate(parsed):
                            if part.lower().startswith('japanese ver'):
                                parsed.pop(i)
                                break
                        other = [other, ' '.join(parsed)]
                else:
                    orig = other
                    inst = False
                    if lc_other.endswith('(inst.)'):
                        inst = True
                        other = other[:-7].strip()

                    if not LangCat.contains_any(other, LangCat.ENG) and LangCat.categorize(other) == LangCat.MIX:
                        try:
                            parsed = ParentheticalParser().parse(other)
                        except Exception:
                            other = orig
                        else:
                            other = ['{}{}'.format(p, ' (Inst.)' if inst else '') for p in parsed] + [orig]
        return other

    def score_match(self, other, *args, normalize=True, **kwargs):
        if normalize:
            other = self._normalize_for_matching(other)
        return super().score_match(other, *args, **kwargs)


def find_ost(artist, title, disco_entry):
    try:
        norm_title_rx = find_ost._norm_title_rx
    except AttributeError:
        norm_title_rx = find_ost._norm_title_rx = re.compile(r'^(.*)\s+(?:Part|Code No)\.?\s*\d+$', re.IGNORECASE)

    orig_title = title
    m = norm_title_rx.match(title)
    if m:
        title = m.group(1).strip()
        if title.endswith(' -'):
            title = title[:-1].strip()
        log.log(2, 'find_ost: normalized {!r} -> {!r}'.format(orig_title, title))

    d_client = DramaWikiClient()
    if artist is not None and not isinstance(artist._client, DramaWikiClient):
        try:
            d_artist = artist.for_alt_site(d_client)
        except (WikiTypeError, WikiEntityInitException):
            pass
        except Exception as e:
            log.debug('Error finding {} version of {}: {}\n{}'.format(d_client._site, artist, e, traceback.format_exc()))
        else:
            ost_match = d_artist.find_song_collection(title)
            if ost_match:
                log.debug('{}: Found OST fuzzy match {!r}={} via artist'.format(artist, title, ost_match), extra={'color': 10})
                return ost_match

    show_title = ' '.join(title.split()[:-1]) if title.endswith(' OST') else title      # Search without 'OST' suffix
    # log.debug('{}: Searching for show {!r} for OST {!r}'.format(artist, show_title, title))

    w_client = WikipediaClient()
    for client in (d_client, w_client):
        search_results = client.search(show_title)
        for link_text, link_uri_path in search_results:
            try:
                series = WikiTVSeries(link_uri_path, client)
            except (WikiTypeError, AmbiguousEntityException):
                pass
            else:
                if not series.matches(show_title):
                    continue
                elif series.ost_hrefs:
                    for ost_href in series.ost_hrefs:
                        ost = WikiSongCollection(ost_href, d_client, disco_entry=disco_entry, artist_context=artist)
                        if len(series.ost_hrefs) == 1 or ost.matches(title):
                            return ost

                for alt_title in series.aka:
                    # log.debug('Found AKA for {!r}: {!r}'.format(show_title, alt_title))
                    alt_uri_path = d_client.normalize_name(alt_title + ' OST')
                    if alt_uri_path:
                        log.debug('Found alternate uri_path for {!r}: {!r}'.format(title, alt_uri_path))
                        return WikiSongCollection(
                            alt_uri_path, d_client, disco_entry=disco_entry, artist_context=artist
                        )

    results = w_client.search(show_title)   # At this point, there was no exact match for this search
    if results:
        # log.debug('Trying to match {!r} to {!r}'.format(show_title, results[0][1]))
        try:
            series = WikiTVSeries(results[0][1], w_client)
        except (WikiTypeError, AmbiguousEntityException):
            pass
        else:
            if series.matches(show_title):
                alt_uri_path = d_client.normalize_name(series.name + ' OST')
                if alt_uri_path:
                    log.debug('Found alternate uri_path for {!r}: {!r}'.format(title, alt_uri_path))
                    return WikiSongCollection(alt_uri_path, d_client, disco_entry=disco_entry, artist_context=artist)

    k_client = KpopWikiClient()
    if disco_entry.get('wiki') == k_client._site and disco_entry.get('uri_path'):
        return WikiSoundtrack(disco_entry['uri_path'], k_client, disco_entry=disco_entry, artist_context=artist)

    return None
