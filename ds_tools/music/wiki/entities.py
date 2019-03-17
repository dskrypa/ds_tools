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
from fuzzywuzzy import fuzz, utils as fuzz_utils

from ...caching import cached, DictAttrProperty, DictAttrPropertyMixin
from ...core import cached_property
from ...http import CodeBasedRestException
from ...unicode import LangCat
from ...utils import soupify
from ..name_processing import eng_cjk_sort, fuzz_process, parse_name, split_name
from .exceptions import *
from .utils import (
    comparison_type_check, edition_combinations, get_page_category, multi_lang_name, sanitize_path, synonym_pattern
)
from .rest import WikiClient, KindieWikiClient, KpopWikiClient, WikipediaClient, DramaWikiClient
from .parsing import *

__all__ = [
    'WikiAgency', 'WikiAlbum', 'WikiArtist', 'WikiDiscography', 'WikiEntity', 'WikiEntityMeta', 'WikiFeatureOrSingle',
    'WikiGroup', 'WikiSinger', 'WikiSongCollection', 'WikiSoundtrack', 'WikiTrack', 'WikiTVSeries'
]
log = logging.getLogger(__name__)

ALBUM_DATED_TYPES = ("Singles", )
ALBUM_MULTI_DISK_TYPES = ("Albums", "Special Albums", "Japanese Albums", "Remake Albums", "Repackage Albums")
ALBUM_NUMBERED_TYPES = ("Album", "Mini Album", "Special Album", "Single Album", "Remake Album", "Repackage Album")
DISCOGRAPHY_TYPE_MAP = {
    'best_albums': 'Compilation',
    'collaborations': 'Collaboration',
    'collaborations_and_features': 'Collaboration',
    'collaboration_single': 'Collaboration',
    'digital_singles': 'Single',
    'features': 'Collaboration',
    'live_albums': 'Live',
    'mini_albums': 'Mini Album',
    'osts': 'Soundtrack',
    'other_releases': 'Single',
    'promotional_singles': 'Single',
    'remake_albums': 'Remake Album',    # Album that contains only covers of other artists' songs
    'repackage_albums': 'Album',
    'single_albums': 'Single Album',
    'singles': 'Single',
    'special_albums': 'Album',
    'special_singles': 'Single',
    'studio_albums': 'Album'
}
JUNK_CHARS = string.whitespace + string.punctuation
NUM_STRIP_TBL = str.maketrans({c: "" for c in "0123456789"})
NUMS = {
    "first": "1st", "second": "2nd", "third": "3rd", "fourth": "4th", "fifth": "5th", "sixth": "6th",
    "seventh": "7th", "eighth": "8th", "ninth": "9th", "tenth": "10th", "debut": "1st"
}
STRIP_TBL = str.maketrans({c: "" for c in JUNK_CHARS})

"""
TODO:
- Search for artist / soloist / soloist of group
- Search for album / song from artist

"""


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
        if not no_fetch:
            if aliases and not name:
                name = aliases if isinstance(aliases, str) else next(filter(None, aliases), None)
                if not name and not uri_path:
                    raise WikiEntityIdentificationException('A uri_path or name is required')

            if disco_entry:
                uri_path = uri_path or disco_entry.get("uri_path")
                name = name or disco_entry.get("title")
                disco_site = disco_entry.get("wiki")
                if disco_site and not client:
                    client = WikiClient.for_site(disco_site)
            elif name and not uri_path:
                client = client or KpopWikiClient()
                if of_group and not isinstance(of_group, WikiGroup):
                    try:
                        of_group = WikiGroup(aliases=of_group)
                    except Exception as e:
                        fmt = 'Error initializing WikiGroup(aliases={!r}) for {}(name={!r}): {}'
                        log.debug(fmt.format(of_group, cls.__name__, name, e))

                if of_group and isinstance(of_group, WikiGroup):
                    if aliases:
                        names = (name, aliases) if isinstance(aliases, str) else tuple(chain((name,), aliases))
                    else:
                        names = (name,)
                    return of_group.find_associated(names)
                elif isinstance(client, KpopWikiClient) and LangCat.contains_any_not(name, LangCat.ENG):
                    key = (uri_path, client, name)
                    obj = WikiEntityMeta._get_match(cls, key, client, cls_cat)
                    if obj is not None:
                        return obj
                    for client in (client, KindieWikiClient()):
                        for link_text, link_href in client.search(name)[:3]:    # Check 1st 3 results for non-eng name
                            entity = cls(link_href, client=client)
                            if entity.matches(name):
                                WikiEntityMeta._instances[key] = entity
                                return entity
                            else:
                                log.log(9, 'Search of {} for {} yielded non-match: {}'.format(client.host, name, entity))
                    else:
                        raise WikiEntityIdentificationException('No matches found for {!r} via search'.format(name))
                else:
                    try:
                        uri_path = client.normalize_name(name)
                    except AmbiguousEntityException as e:
                        if e.alternatives and aliases:
                            for alt in e.alternatives:
                                alt_obj = cls(alt)
                                if alt_obj.matches(aliases):
                                    return alt_obj
                        raise e
                    except CodeBasedRestException as e:
                        if e.code == 404 and orig_client is None:
                            client = WikipediaClient()
                            uri_path = client.normalize_name(name)
                        else:
                            raise e
            elif name and uri_path and uri_path.startswith("//"):   # Alternate subdomain of fandom.com
                uri_path = None

            if uri_path and uri_path.startswith(("http://", "https://")):
                _url = urlparse(uri_path)
                if client is None:
                    client = WikiClient.for_site(_url.hostname)
                elif client and client._site != _url.hostname:
                    fmt = "The provided client is for {!r}, but the URL requires a client for {!r}: {}"
                    raise ValueError(fmt.format(client._site, _url.hostname, uri_path))
                uri_path = _url.path[6:] if _url.path.startswith("/wiki/") else _url.path
            elif client is None:
                client = KpopWikiClient()

        if no_type_check or no_fetch:
            obj = cls.__new__(cls, uri_path, client)
            # noinspection PyArgumentList
            obj.__init__(uri_path, client, name=name, disco_entry=disco_entry, no_fetch=no_fetch, **kwargs)
            return obj

        is_feat_collab = disco_entry and disco_entry.get("base_type") in ("features", "collaborations", "singles")
        if uri_path or is_feat_collab:
            uri_path = client.normalize_name(uri_path) if uri_path and " " in uri_path else uri_path
            key = (uri_path, client, name)
            obj = WikiEntityMeta._get_match(cls, key, client, cls_cat)
            if obj is not None:
                return obj
            elif not uri_path and is_feat_collab:
                category, url, raw = "collab/feature/single", None, None
            else:
                url = client.url_for(uri_path)
                # Note: client.get_entity_base caches args->return vals
                raw, cats = client.get_entity_base(uri_path, cls_cat.title() if isinstance(cls_cat, str) else None)
                category = get_page_category(url, cats)

            # noinspection PyTypeChecker
            WikiEntityMeta._check_type(cls, url, category, cls_cat)
            exp_cls = WikiEntityMeta._category_classes.get(category)
        else:
            exp_cls = cls
            raw = None
            key = (uri_path, client, name)

        if key not in WikiEntityMeta._instances:
            obj = exp_cls.__new__(exp_cls, uri_path, client)
            # noinspection PyArgumentList
            obj.__init__(uri_path, client, name=name, raw=raw, disco_entry=disco_entry, **kwargs)
            WikiEntityMeta._instances[key] = obj
        else:
            obj = WikiEntityMeta._instances[key]

        if of_group:
            if isinstance(obj, WikiSinger) and obj.member_of is None or not obj.member_of.matches(of_group):
                fmt = "Found {} for uri_path={!r}, name={!r}, but they are a member_of={}, not of_group={!r}"
                raise WikiEntityIdentificationException(fmt.format(obj, uri_path, name, obj.member_of, of_group))
            elif isinstance(obj, WikiGroup) and obj.subunit_of is None or not obj.subunit_of.matches(of_group):
                fmt = "Found {} for uri_path={!r}, name={!r}, but they are a subunit_of={}, not of_group={!r}"
                raise WikiEntityIdentificationException(fmt.format(obj, uri_path, name, obj.subunit_of, of_group))
            else:
                raise WikiTypeError("{} is a {}, so cannot be of_group={}".format(obj, type(obj).__name__, of_group))

        return obj

    @staticmethod
    def _get_match(cls, key, client, cls_cat):
        if key in WikiEntityMeta._instances:
            inst = WikiEntityMeta._instances[key]
            if cls_cat and ((inst._category == cls_cat) or (inst._category in cls_cat)):
                return inst
            else:
                WikiEntityMeta._check_type(cls, client.url_for(inst._uri_path), inst._category, cls_cat)
        return None

    @staticmethod
    def _check_type(cls, url, category, cls_cat):
        exp_cls = WikiEntityMeta._category_classes.get(category)
        exp_base = WikiEntityMeta._category_bases.get(category)
        has_unexpected_cls = exp_cls and not issubclass(exp_cls, cls) and cls._category is not None
        has_unexpected_base = exp_base and not issubclass(cls, exp_base) and cls._category is not None
        if has_unexpected_cls or has_unexpected_base or (exp_cls is None and exp_base is None):
            article = "an" if category and category[0] in "aeiou" else "a"
            # exp_cls_strs = (getattr(exp_cls, "__name__", None), getattr(exp_base, "__name__", None))
            # log.debug("Specified cls={}, exp_cls={}, exp_base={}".format(cls.__name__, *exp_cls_strs))
            raise WikiTypeError(url, article, category, cls_cat, cls)


class WikiEntity(metaclass=WikiEntityMeta):
    _int_pat = re.compile(r"(?P<int>\d+)|(?P<other>\D+)")
    __instances = {}
    _categories = {}
    _category = None

    def __init__(self, uri_path=None, client=None, *, name=None, raw=None, no_fetch=False, **kwargs):
        self._client = client
        self._uri_path = uri_path
        self._raw = raw if raw is not None else client.get_page(uri_path) if uri_path and not no_fetch else None
        self.name = name or uri_path

    def __repr__(self):
        return "<{}({!r})>".format(type(self).__name__, self.name)

    def __eq__(self, other):
        if not isinstance(other, WikiEntity):
            return False
        return self.name == other.name and self._raw == other._raw

    def __hash__(self):
        return hash((self.name, self._raw))

    @cached_property
    def aliases(self):
        aliases = (getattr(self, attr, None) for attr in ("english_name", "cjk_name", "stylized_name", "aka", "name"))
        return [a for a in aliases if a]

    @cached_property
    def lc_aliases(self):
        return [a.lower() for a in self.aliases]

    @cached_property
    def _fuzzed_aliases(self):
        return set(filter(None, (fuzz_process(a) for a in self.aliases)))

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
            return self == other
        others = (other,) if isinstance(other, str) else other
        fuzzed_others = tuple(filter(None, (fuzz_process(o) for o in others) if process else others))
        if not fuzzed_others:
            log.warning('Unable to compare {} to {!r}: nothing to compare after processing'.format(self, other))
            return False
        return bool(self._fuzzed_aliases.intersection(fuzzed_others))

    def score_match(self, other, process=True, track=None, disk=None, year=None):
        """
        Score how closely this WikiEntity's aliases match the given strings.

        :param str|Iterable other: String or iterable that yields strings
        :param bool process:
        :param int|None track: The track number if other represents a track
        :param int|none disk: The disk number if other represents a track
        :param int|None year: The release year if other represents an album
        :return tuple: (score, best alias of this WikiEntity, best value from other)
        """
        others = (other,) if isinstance(other, str) else other
        fuzzed_others = tuple(filter(None, (fuzz_process(o) for o in others) if process else others))
        if not fuzzed_others:
            log.warning('Unable to compare {} to {!r}: nothing to compare after processing'.format(self, other))
            return 0, None, None

        scorer = fuzz.WRatio if isinstance(self, WikiSongCollection) else fuzz.token_sort_ratio
        int_pat = self._int_pat
        # noinspection PyUnresolvedReferences
        self_nums = ''.join(m.groups()[0] for m in iter(int_pat.scanner(self.name).match, None) if m.groups()[0])

        score_mod = 0
        if track is not None and isinstance(self, WikiTrack):
            score_mod += 15 if self.num == track else -15
        if disk is not None and isinstance(self, WikiTrack):
            score_mod += 15 if self.disk == disk else -15
        if year is not None and isinstance(self, WikiSongCollection):
            try:
                years_match = self.released.year == int(year)
            except Exception:
                pass
            else:
                score_mod += 15 if years_match else -15

        best_score, best_alias, best_val = 0, None, None
        for alias in self._fuzzed_aliases:
            for val in fuzzed_others:
                if best_score >= 100:
                    break
                score = scorer(alias, val, force_ascii=False, full_process=False)
                # noinspection PyUnresolvedReferences
                val_nums = ''.join(m.groups()[0] for m in iter(int_pat.scanner(val).match, None) if m.groups()[0])
                if val_nums != self_nums:
                    score -= 40
                if ("live" in alias and "live" not in val) or ("live" in val and "live" not in alias):
                    score -= 25
                if score > best_score:
                    best_score, best_alias, best_val = score, alias, val

        return best_score + score_mod, best_alias, best_val

    @property
    def _soup(self):
        # soupify every time so that elements may be modified/removed without affecting other functions
        return soupify(self._raw, parse_only=bs4.SoupStrainer("div", id="mw-content-text")) if self._raw else None

    @cached_property
    def _side_info(self):
        """The parsed 'aside' / 'infobox' section of this page"""
        if not hasattr(self, "_WikiEntity__side_info"):
            _ = self._clean_soup

        try:
            return {} if not self.__side_info else self._client.parse_side_info(self.__side_info)
        except Exception as e:
            log.error("Error processing side bar info for {}: {}".format(self._uri_path, e))
            raise e

    @cached_property
    def _clean_soup(self):
        """The soupified page content, with the undesirable parts at the beginning removed"""
        try:
            content = self._soup.find("div", id="mw-content-text")
        except AttributeError as e:
            self.__side_info = None
            log.warning(e)
            return None

        if isinstance(self._client, (KpopWikiClient, KindieWikiClient)):
            aside = content.find("aside")
            # if aside:
            #     log.debug("Extracting aside")
            self.__side_info = aside.extract() if aside else None

            for ele_name in ("center",):
                rm_ele = content.find(ele_name)
                if rm_ele:
                    # log.debug("Extracting: {}".format(rm_ele))
                    rm_ele.extract()

            for clz in ("dablink", "hatnote", "shortdescription", "infobox"):
                rm_ele = content.find(class_=clz)
                if rm_ele:
                    # log.debug("Extracting: {}".format(rm_ele))
                    rm_ele.extract()

            for rm_ele in content.find_all(class_="mw-empty-elt"):
                # log.debug("Extracting: {}".format(rm_ele))
                rm_ele.extract()

            first_ele = content.next_element
            if getattr(first_ele, "name", None) == "dl":
                # log.debug("Extracting: {}".format(first_ele))
                first_ele.extract()
        elif isinstance(self._client, DramaWikiClient):
            self.__side_info = None
            for clz in ("toc",):
                rm_ele = content.find(class_=clz)
                if rm_ele:
                    rm_ele.extract()

            for clz in ("toc", "mw-editsection"):
                for rm_ele in content.find_all(class_=clz):
                    rm_ele.extract()
        elif isinstance(self._client, WikipediaClient):
            for rm_ele in content.select("[style~=\"display:none\"]"):
                rm_ele.extract()

            infobox = content.find("table", class_=re.compile("infobox.*"))
            self.__side_info = infobox.extract() if infobox else None

            for rm_ele in content.find_all(class_="mw-empty-elt"):
                rm_ele.extract()

            for clz in ("toc", "mw-editsection", "reference"):
                for rm_ele in content.find_all(class_=clz):
                    rm_ele.extract()

            for clz in ("shortdescription",):
                rm_ele = content.find(class_=clz)
                if rm_ele:
                    rm_ele.extract()
        else:
            log.debug("No sanitization configured for soup objects from {}".format(type(self._client).__name__))
        return content


class WikiAgency(WikiEntity):
    _category = "agency"


class WikiDiscography(WikiEntity):
    _category = "discography"

    def __init__(self, uri_path=None, client=None, *, artist=None, **kwargs):
        super().__init__(uri_path, client, **kwargs)
        self.artist = artist
        self._albums, self._singles = parse_discography_page(self._uri_path, self._clean_soup, artist)

    @cached_property
    def _soundtracks(self):
        soundtracks = defaultdict(list)
        for group in self._singles:
            if group["sub_type"] and "soundtrack" in group["sub_type"]:
                for track in group["tracks"]:
                    soundtracks[track["album"]].append(track)
        return soundtracks


class WikiTVSeries(WikiEntity):
    _category = "tv_series"

    def __init__(self, uri_path=None, client=None, **kwargs):
        super().__init__(uri_path, client, **kwargs)

        self.ost_href = None
        if self._side_info:
            self.name = self._side_info["name"]
            self.aka = self._side_info.get("also known as", [])
        elif isinstance(self._client, DramaWikiClient):
            ul = self._clean_soup.find(id="Details").parent.find_next("ul")
            self._info = parse_drama_wiki_info_list(self._uri_path, ul)
            self.english_name, self.cjk_name = self._info["title"]
            self.name = multi_lang_name(self.english_name, self.cjk_name)
            self.aka = self._info.get("also known as", [])
            ost = self._info.get("original soundtrack")
            if ost:
                self.ost_href = list(ost.values())[0]
        else:
            self.aka = []


class WikiArtist(WikiEntity):
    _category = ("group", "singer")
    _known_artists = set()
    __known_artists_loaded = False

    def __init__(self, uri_path=None, client=None, *, name=None, strict=True, **kwargs):
        super().__init__(uri_path, client, **kwargs)
        self.english_name, self.cjk_name, self.stylized_name, self.aka = None, None, None, None
        if self._raw:
            try:
                name_parts = parse_name(self._clean_soup.text)
            except Exception as e:
                if strict:
                    raise e
                log.warning("{} while processing intro for {}: {}".format(type(e).__name__, name or uri_path, e))
            else:
                self.english_name, self.cjk_name, self.stylized_name, self.aka, self._info = name_parts
        if name and not any(val for val in (self.english_name, self.cjk_name, self.stylized_name)):
            self.english_name, self.cjk_name = split_name(name)

        self.name = multi_lang_name(self.english_name, self.cjk_name)
        if self.english_name and isinstance(self._client, KpopWikiClient):
            type(self)._known_artists.add(self.english_name.lower())

    def __repr__(self):
        try:
            return "<{}({!r})>".format(type(self).__name__, self.stylized_name or self.name)
        except AttributeError as e:
            return "<{}({!r})>".format(type(self).__name__, self._uri_path)

    def __lt__(self, other):
        comparison_type_check(self, other, (WikiArtist, str), "<")
        return (self.name < other.name) if isinstance(other, WikiArtist) else (self.name < other)

    def __gt__(self, other):
        comparison_type_check(self, other, (WikiArtist, str), ">")
        return (self.name > other.name) if isinstance(other, WikiArtist) else (self.name > other)

    @classmethod
    def known_artist_eng_names(cls):
        if not cls.__known_artists_loaded:
            cls.__known_artists_loaded = True
            known_artists_path = Path(__file__).resolve().parents[3].joinpath("music/artist_dir_to_artist.json")
            with open(known_artists_path.as_posix(), "r", encoding="utf-8") as f:
                artists = json.load(f)
            cls._known_artists.update((split_name(artist)[0].lower() for artist in artists.values()))
        return cls._known_artists

    @classmethod
    def known_artists(cls):
        for name in sorted(cls.known_artist_eng_names()):
            yield WikiArtist(name=name)

    @cached_property
    def _alt_entities(self):
        pages = []
        for client_cls in (KpopWikiClient, WikipediaClient):
            if not isinstance(self._client, client_cls):
                try:
                    page = WikiArtist(None, client_cls(), name=self._uri_path)
                except Exception as e:
                    log.debug("Unable to retrieve alternate {} entity for {}: {}".format(client_cls.__name__, self, e))
                else:
                    pages.append(page)
        return pages

    @cached_property
    def _disco_page(self):
        name = self._uri_path.title() + "_discography"
        try:
            return WikiDiscography(None, WikipediaClient(), name=name, artist=self)
        except Exception as e:
            fmt = "Unable to retrieve alternate discography page for {}: {}{}"
            # log.debug(fmt.format(self, e, "\n" + traceback.format_exc()))
            log.debug(fmt.format(self, e))
        return None

    @property
    def _discography(self):
        try:
            discography_h2 = self._clean_soup.find("span", id="Discography").parent
        except AttributeError as e:
            log.error("No page content / discography was found for {}".format(self))
            return []

        entries = []
        h_levels = {"h3": "language", "h4": "type"}
        lang, album_type = "Korean", "Unknown"
        ele = discography_h2.next_sibling
        while True:
            while not isinstance(ele, bs4.element.Tag):     # Skip past NavigableString objects
                if ele is None:
                    return entries
                ele = ele.next_sibling

            val_type = h_levels.get(ele.name)
            if val_type == "language":                      # *almost* always h3, but sometimes type is h3
                val = next(ele.children).get("id")
                val_lc = val.lower()
                if any(v in val_lc for v in ("album", "single", "collaboration", "feature")):
                    h_levels[ele.name] = "type"
                    album_type = val
                else:
                    lang = val
            elif val_type == "type":
                album_type = next(ele.children).get("id")
            elif ele.name == "ul":
                li_eles = list(ele.children)
                top_level_li_eles = li_eles.copy()
                num = 0
                while li_eles:
                    li = li_eles.pop(0)
                    if li in top_level_li_eles:
                        num += 1
                    ul = li.find("ul")
                    if ul:
                        ul.extract()                            # remove nested list from tree
                        li_eles = list(ul.children) + li_eles   # insert elements from the nested list at top

                    entry = parse_discography_entry(self, li, album_type, lang, num)
                    if entry:
                        entries.append(entry)

            elif ele.name in ("h2", "div"):
                break
            ele = ele.next_sibling
        return entries

    @cached_property
    def discography(self):
        discography = []
        for entry in self._discography:
            if entry["is_ost"]:
                client = WikiClient.for_site("wiki.d-addicts.com")
                title = entry["title"]
                m = re.match("^(.*)\s+(?:Part|Code No)\.?\s*\d+$", title, re.IGNORECASE)
                if m:
                    title = m.group(1).strip()
                uri_path = client.normalize_name(title)
                # log.debug("Normalized title={!r} => uri_path={!r}".format(title, uri_path))
            else:
                client = WikiClient.for_site(entry["wiki"])
                uri_path = entry["uri_path"]
                title = entry["title"]

            cls = WikiSongCollection
            if not uri_path:
                base_type = entry.get("base_type")
                if base_type == "osts":
                    cls = WikiSoundtrack
                elif any(val in base_type for val in ("singles", "collaborations", "features")):
                    cls = WikiFeatureOrSingle
                elif "albums" in base_type:
                    cls = WikiAlbum
                else:
                    log.debug("{}: Unexpected base_type={!r} for {}".format(self, base_type, entry), extra={"color": 9})

            try:
                try:
                    discography.append(cls(uri_path, client, disco_entry=entry, artist_context=self))
                except CodeBasedRestException as http_e:
                    if entry["is_ost"]:
                        ost = find_ost(self, title, entry)
                        if ost:
                            discography.append(ost)
                        else:
                            log.debug("{}: Unable to find wiki page or alternate matches for {}".format(self, entry))
                            ost = cls(uri_path, client, disco_entry=entry, artist_context=self, no_fetch=True)
                            discography.append(ost)
                            # raise http_e
                    else:
                        log.debug("{}: Unable to find wiki page for {}".format(self, entry))
                        alb = cls(uri_path, client, disco_entry=entry, artist_context=self, no_fetch=True)
                        discography.append(alb)
                        # raise http_e
            except MusicWikiException as e:
                fmt = "{}: Error processing discography entry for {!r} / {!r}: {}"
                log.error(fmt.format(self, entry["uri_path"], entry["title"], e), extra={"color": 13})
                raise e

        return discography

    @cached_property
    def soundtracks(self):
        return [album for album in self.discography if isinstance(album, WikiSoundtrack)]

    @cached_property
    def expected_rel_path(self):
        return Path(sanitize_path(self.english_name))

    @cached_property
    def associated_acts(self):
        associated = []
        for text, href in self._side_info.get('associated', {}).items():
            associated.append(WikiArtist(href, name=text, client=self._client))
        return associated


class WikiGroup(WikiArtist):
    _category = "group"

    def __init__(self, uri_path=None, client=None, **kwargs):
        super().__init__(uri_path, client, **kwargs)
        self.subunit_of = None

        clean_soup = self._clean_soup
        if re.search("^.* is (?:a|the) .*?sub-?unit of .*?group", clean_soup.text.strip()):
            for i, a in enumerate(clean_soup.find_all("a")):
                href = a.get("href") or ""
                href = href[6:] if href.startswith("/wiki/") else href
                if href and (href != self._uri_path):
                    self.subunit_of = WikiGroup(href)
                    break

    @cached_property
    def members(self):
        members_h2 = self._clean_soup.find("span", id="Members").parent
        members_container = members_h2
        for sibling in members_h2.next_siblings:
            if sibling.name in ('ul', 'table'):
                members_container = sibling
                break

        members = []
        if members_container.name == "ul":
            for li in members_container.find_all("li"):
                a = li.find("a")
                href = a.get("href") if a else None
                if href:
                    members.append(WikiSinger(href[6:] if href.startswith("/wiki/") else href))
                else:
                    m = re.match("(.*?)\s*-\s*(.*)", li.text)
                    member = list(map(str.strip, m.groups()))[0]
                    members.append(member)
        elif members_container.name == "table":
            for tr in members_container.find_all("tr"):
                if tr.find("th"):
                    continue
                a = tr.find("a")
                href = a.get("href") if a else None
                # log.debug('{}: Found member tr={}, href={!r}'.format(self, tr, href))
                if href:
                    members.append(WikiSinger(href[6:] if href.startswith("/wiki/") else href))
                else:
                    member = list(map(str.strip, (td.text.strip() for td in tr.find_all("td"))))[0]
                    members.append(member)
        return members

    @cached_property
    def sub_units(self):
        su_ele = self._clean_soup.find(id=re.compile("sub[-_]?units", re.IGNORECASE))
        if not su_ele:
            return []

        while su_ele and not su_ele.name.startswith("h"):
            su_ele = su_ele.parent
        ul = su_ele.next_sibling.next_sibling
        if not ul or ul.name != "ul":
            raise RuntimeError("Unexpected sibling element for sub-units")

        sub_units = []
        for li in ul.find_all("li"):
            a = li.find("a")
            href = a.get("href") if a else None
            if href:
                sub_units.append(WikiGroup(href[6:] if href.startswith("/wiki/") else href))
        return sub_units

    def find_associated(self, name):
        for member in self.members:
            if member.matches(name):
                return member
        for sub_unit in self.sub_units:
            if sub_unit.matches(name):
                return sub_unit
        for artist in self.associated_acts:
            if artist.matches(name):
                return artist
        raise MemberDiscoveryException('Unable to find member or sub-unit of {} named {!r}'.format(self, name))


class WikiSinger(WikiArtist):
    _category = "singer"

    def __init__(self, uri_path=None, client=None, **kwargs):
        super().__init__(uri_path, client, **kwargs)
        self.member_of = None

        clean_soup = self._clean_soup
        mem_pat = r"^.* is (?:a|the) (.*?)(?:member|vocalist|rapper|dancer|leader|visual|maknae) of .*?group (.*)\."
        mem_match = re.search(mem_pat, clean_soup.text.strip())
        if mem_match:
            if "former" not in mem_match.group(1):
                group_name = mem_match.group(2)
                m = re.match(r"^(.*)\.\s+[A-Z]", group_name)
                if m:
                    group_name = m.group(1)
                # log.debug("{} appears to be a member of group {!r}; looking for group page...".format(self, group_name))
                for i, a in enumerate(clean_soup.find_all("a")):
                    if a.text and a.text in group_name:
                        href = (a.get("href") or "")[6:]
                        # log.debug("{}: May have found group match for {!r} => {!r}, href={!r}".format(self, group_name, a.text, href))
                        if href and (href != self._uri_path):
                            try:
                                self.member_of = WikiGroup(href)
                            except WikiTypeError as e:
                                fmt = "{}: Found possible group match for {!r}=>{!r}, href={!r}, but {}"
                                log.debug(fmt.format(self, group_name, a.text, href, e))
                            else:
                                break

        eng_first, eng_last, cjk_eng_first, cjk_eng_last = None, None, None, None
        for eng, cjk in self._side_info.get('birth_name', []):
            if eng and cjk:
                cjk_eng_last, cjk_eng_first = eng.split(maxsplit=1)
                self.aliases.extend((eng, cjk))
            elif eng:
                eng_first, eng_last = eng.rsplit(maxsplit=1)
                self.aliases.extend((eng, eng_first))
                self.__add_aliases(eng_first)
            elif cjk:
                self.aliases.append(cjk)

        if cjk_eng_first or cjk_eng_last:
            if eng_last:
                eng_first = cjk_eng_first if eng_last == cjk_eng_last else cjk_eng_last
                self.aliases.append(eng_first)
                self.__add_aliases(eng_first)
            else:
                self.aliases.append(cjk_eng_first)

        if self.english_name:
            self.__add_aliases(self.english_name)

        try:
            del self.__dict__['lc_aliases']
        except KeyError:
            pass

    def __add_aliases(self, name):
        for c in ' -':
            if c in name:
                name_split = name.split(c)
                for k in ('', ' ', '-'):
                    joined = k.join(name_split)
                    if joined not in self.aliases:
                        self.aliases.append(joined)


class WikiSongCollection(WikiEntity):
    _category = ("album", "soundtrack", "collab/feature/single")
    _part_rx = re.compile(r"(?:part|code no)\.?\s*", re.IGNORECASE)
    _bonus_rx = re.compile(r"^(.*)\s+bonus tracks?$", re.IGNORECASE)

    def __init__(self, uri_path=None, client=None, *, disco_entry=None, album_info=None, artist_context=None, **kwargs):
        super().__init__(uri_path, client, **kwargs)
        self._discography_entry = disco_entry or {}
        self.english_name, self.cjk_name, self.stylized_name, self.aka, self._info = None, None, None, None, None
        self._album_info = album_info or {}
        self._albums = []
        self._primary_artist = None
        self._intended = None
        self._artist_context = artist_context
        if isinstance(self._client, DramaWikiClient) or kwargs.get("no_init"):
            return
        elif self._raw:
            self._albums = albums = self._client.parse_album_page(self._uri_path, self._clean_soup, self._side_info)
            artist = self._side_info.get("artist", {})
            if len(artist) == 1:
                self._primary_artist = next(iter(artist.items()))

            if len(albums) > 1:
                err_base = "{} contains both original+repackaged album info on the same page".format(uri_path)
                if not disco_entry:
                    msg = "{} - a discography entry is required to identify it".format(err_base)
                    raise WikiEntityIdentificationException(msg)

                d_title = disco_entry.get("title")
                d_lc_title = d_title.lower()
                try:
                    d_artist_name, d_artist_uri_path = disco_entry.get("primary_artist")    # tuple(name, uri_path)
                except TypeError as e:
                    d_artist_name, d_artist_uri_path = None, None
                    d_no_artist = True
                else:
                    d_no_artist = False
                d_lc_artist = d_artist_name.lower() if d_artist_name else ""

                if d_no_artist or d_artist_uri_path in artist.values() or d_lc_artist in map(str.lower, artist.keys()):
                    for album in albums:
                        if d_lc_title in map(str.lower, map(str, album["title_parts"])):
                            self._album_info = album
                else:               # Likely linked as a collaboration
                    for package in self.packages:
                        for edition, disk, tracks in package.editions_and_disks:
                            for track in tracks:
                                track_name = track.long_name.lower()
                                if d_lc_title in track_name and d_lc_artist in track_name:
                                    fmt = "Matched {!r} - {!r} to {} as a collaboration"
                                    log.debug(fmt.format(d_artist_name, d_title, package))
                                    self._album_info = package._album_info
                                    self._intended = edition, disk, track

                if not self._album_info:
                    msg = "{}, and it could not be matched with discography entry: {}".format(err_base, disco_entry)
                    raise WikiEntityIdentificationException(msg)
            else:
                self._album_info = albums[0]

            self.english_name, self.cjk_name, self.stylized_name, self.aka, self._info = self._album_info["title_parts"]
        elif disco_entry:
            self._primary_artist = disco_entry.get("primary_artist")
            try:
                self.english_name, self.cjk_name = eng_cjk_sort(disco_entry["title"])
            except Exception as e:
                msg = "Unable to find valid title in discography entry: {}".format(disco_entry)
                raise WikiEntityInitException(msg) from e
        else:
            msg = "A valid uri_path / discography entry are required to initialize a {}".format(type(self).__name__)
            raise WikiEntityInitException(msg)

        self._track_lists = self._album_info.get("track_lists")
        if self._track_lists is None:
            album_tracks = self._album_info.get("tracks")
            if album_tracks:
                self._track_lists = [album_tracks]

        self.name = multi_lang_name(self.english_name, self.cjk_name)
        if self._info:
            self.name = " ".join(chain((self.name,), map("({})".format, self._info)))

        if self._raw and isinstance(self._client, KpopWikiClient) and not disco_entry and not artist_context:
            artist = None
            try:
                artist = self.artist
            except AttributeError:
                try:
                    artist = self.artists[0]
                except IndexError:
                    pass
            finally:
                for key in ("artists", "_artists", "artist"):
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
        comparison_type_check(self, other, WikiSongCollection, "<")
        return self.name < other.name

    def __gt__(self, other):
        comparison_type_check(self, other, WikiSongCollection, ">")
        return self.name > other.name

    @cached_property
    def released(self):
        return self._album_info.get('released')

    @cached_property
    def year(self):
        return self._discography_entry.get('year')

    @cached_property
    def album_type(self):
        return DISCOGRAPHY_TYPE_MAP[self._discography_entry.get("base_type")]

    @cached_property
    def album_num(self):
        return self._discography_entry.get("num")

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

    @cached_property
    def expected_rel_dir(self):
        numbered_type = self.album_type in ALBUM_NUMBERED_TYPES
        if numbered_type or self.album_type in ('Single', ):
            release_date = self._album_info["released"].strftime("%Y.%m.%d")
            if numbered_type:
                title = '[{}] {} [{}]'.format(release_date, self.title, self.num_and_type)
            else:
                title = '[{}] {}'.format(release_date, self.title)
        else:
            title = self.title

        return Path(self.album_type + 's').joinpath(sanitize_path(title)).as_posix()

    @cached_property
    def expected_rel_path(self):
        return self.artist.expected_rel_path.joinpath(self.expected_rel_dir)

    @cached_property
    def _artists(self):
        """dict(artist.lower(): uri_path)"""
        artists = {self._primary_artist[0].lower(): self._primary_artist[1]} if self._primary_artist else {}
        # d_collabs = self._discography_entry.get("collaborators", {})
        d_collabs = self._discography_entry.get("collaborators", [])

        a_artists = self._album_info.get("artists", {})
        # for artist, href in chain(d_collabs.items(), a_artists.items()):
        for artist, href in a_artists.items():
            artist = artist.lower()
            if not artists.get(artist):
                artists[artist] = href[6:] if href and href.startswith("/wiki/") else href

        for collab in d_collabs:
            artist = collab["artist"][0].lower()
            if not artists.get(artist):
                artists[artist] = collab.get("artist_href")

        return artists

    @cached_property
    def artists(self):
        artists = set()
        for name, href in self._artists.items():
            if name.lower() in ("various artists", "various"):
                continue
            try:
                artist = WikiArtist(href, name=name)
            except AmbiguousEntityException as e:
                if self._artist_context and isinstance(self._artist_context, WikiGroup):
                    found = False
                    for member in self._artist_context.members:
                        if member._uri_path in e.alternatives:
                            artists.add(member)
                            found = True
                            break
                    if found:
                        continue

                fmt = "{}'s artist={!r} is ambiguous"
                no_warn = False
                if e.alternatives:
                    fmt += " - it could be one of: {}".format(" | ".join(e.alternatives))
                    if len(e.alternatives) == 1:
                        alt_href = e.alternatives[0]
                        try:
                            alt_entity = WikiEntity(alt_href)
                        except Exception:
                            pass
                        else:
                            if not isinstance(alt_entity, WikiArtist):
                                fmt = "{}'s artist={!r} has no page in {}; the disambiguation alternative was {}"
                                log.debug(fmt.format(self, name, alt_entity._client.host, alt_entity))
                                no_warn = True

                if not no_warn:
                    log.warning(fmt.format(self, name), extra={"color": (11, 9)})

                artists.add(WikiArtist(href, name=name, no_fetch=True))
            except CodeBasedRestException as e:
                if not isinstance(self._client, KpopWikiClient):
                    try:
                        artist = WikiArtist(name=name, client=self._client)
                    except CodeBasedRestException as e2:
                        fmt = "Error retrieving info for {}'s artist={!r} (href={!r}) from both {} and {}: {}"
                        log.error(fmt.format(self, name, href, self._client, KpopWikiClient(), e), extra={"color": 13})
                        artists.add(WikiArtist(href, name=name, no_fetch=True))
                    else:
                        artists.add(artist)
                else:
                    msg = "Error retrieving info for {}'s artist={!r} (href={!r}): {}".format(self, name, href, e)
                    if href is None:
                        log.log(9, msg)
                    else:
                        log.error(msg, extra={"color": 13})
                    artists.add(WikiArtist(href, name=name, no_fetch=True))
            except WikiTypeError as e:
                #no_type_check
                if e.category == "disambiguation":
                    fmt = "{}'s artist={!r} has an ambiguous href={}"
                    log.warning(fmt.format(self, name, e.url), extra={"color": (11, 9)})
                    artists.add(WikiArtist(href, name=name, no_fetch=True))
                else:
                    raise e
            else:
                artists.add(artist)
        return sorted(artists)

    @cached_property
    def artist(self):
        if self._primary_artist:
            return WikiArtist(self._primary_artist[1], name=self._primary_artist[0])

        artists = self.artists
        if len(artists) == 1:
            return artists[0]
        elif self._artist_context:
            return self._artist_context
        raise AttributeError("{} has multiple contributing artists and no artist context".format(self))

    @cached_property
    def _editions_by_disk(self):
        editions_by_disk = defaultdict(list)
        for track_section in self._track_lists:
            editions_by_disk[track_section.get("disk")].append(track_section)
        return editions_by_disk

    def _get_tracks(self, edition_or_part=None, disk=None):
        if self._track_lists:
            # log.debug("{}: Retrieving tracks for edition_or_part={!r}".format(self, edition_or_part))
            if disk is None and edition_or_part is None or isinstance(edition_or_part, int):
                edition_or_part = edition_or_part or 0
                try:
                    return self._track_lists[edition_or_part]
                except IndexError as e:
                    msg = "{} has no part/edition called {!r}".format(self, edition_or_part)
                    raise InvalidTrackListException(msg) from e

            editions = self._editions_by_disk[disk or 1]
            if not editions and disk is None:
                editions = self._editions_by_disk[disk]
            if not editions:
                raise InvalidTrackListException("{} has no disk {}".format(self, disk))
            elif edition_or_part is None:
                return editions[0]

            # noinspection PyUnresolvedReferences
            lc_ed_or_part = edition_or_part.lower()
            is_part = lc_ed_or_part.startswith(("part", "code no"))
            if is_part:
                lc_ed_or_part = self._part_rx.sub("part ", lc_ed_or_part)

            bonus_match = None
            for i, edition in enumerate(editions):
                name = (edition.get("section") or "").lower()
                if name == lc_ed_or_part or (is_part and lc_ed_or_part in self._part_rx.sub("part ", name)):
                    return edition
                else:
                    m = self._bonus_rx.match(name)
                    if m and m.group(1).strip() == lc_ed_or_part:
                        bonus_match = i
                        # log.debug("bonus_match={}: {}".format(bonus_match, edition))
                        break

            if bonus_match is not None:
                edition = editions[bonus_match]
                first_track = min(t["num"] for t in edition["tracks"])
                if first_track == 1:
                    return edition
                name = self._bonus_rx.match(edition["section"]).group(1).strip()
                combined = {
                    "section": name, "tracks": edition["tracks"].copy(), "disk": edition.get("disk"),
                    "links": edition.get("links", [])
                }

                combos = edition_combinations(editions[:bonus_match], first_track)
                # log.debug("Found {} combos".format(len(combos)))
                if len(combos) != 1:
                    # for combo in combos:
                    #     tracks = sorted(t["num"] for t in chain.from_iterable(edition["tracks"] for edition in combo))
                    #     log.debug("Combo: {} => {}".format(", ".join(repr(e["section"]) for e in combo), tracks))
                    raise InvalidTrackListException("{}: Unable to reconstruct {!r}".format(self, name))

                for edition in combos[0]:
                    combined["tracks"].extend(edition["tracks"])
                    combined["links"].extend(edition.get("links", []))

                combined["tracks"] = sorted(combined["tracks"], key=lambda t: t["num"])
                combined["links"] = sorted(set(combined["links"]))
                return combined
            raise InvalidTrackListException("{} has no part/edition called {!r}".format(self, edition_or_part))
        else:
            if "single" in self.album_type.lower():
                return {"tracks": [{"name_parts": (self.english_name, self.cjk_name)}]}
            else:
                log.log(9, "No page content found for {} - returning empty track list".format(self), extra={"color": 8})
                return {"tracks": []}

    @cached(True)
    def get_tracks(self, edition_or_part=None, disk=None):
        if self._intended is not None and edition_or_part is None and disk is None:
            if len(self._intended) == 3:
                return [WikiTrack(self._intended[2]._info, self, self._artist_context)]
            elif len(self._intended) == 2:
                # noinspection PyTupleAssignmentBalance
                edition_or_part, disk = self._intended
        _tracks = self._get_tracks(edition_or_part, disk)
        return [WikiTrack(info, self, self._artist_context) for info in _tracks["tracks"]]

    @cached_property
    def editions_and_disks(self):
        bonus_rx = re.compile("^(.*)\s+bonus tracks?$", re.IGNORECASE)
        editions = []
        for edition in self._track_lists:
            section = edition.get("section")
            m = bonus_rx.match(section or "")
            name = m.group(1).strip() if m else section
            disk = edition.get("disk")
            editions.append((name, disk, self.get_tracks(name, disk)))
        return editions

    @cached_property
    def packages(self):
        if len(self._albums) == 1:
            return [self]
        elif len(self._artists) > 1:
            fmt = "Packages can only be retrieved for {} objects with 1 packaging or a primary artist"
            raise AttributeError(fmt.format(type(self).__name__))

        try:
            artist = next(iter(self._artists.items()))
        except Exception as e:
            log.error("Unable to get artist from {} / {}".format(self, self._artists))
            raise e

        packages = []
        for album in self._albums:
            disco_entry = {"title": album["title_parts"][0], "artist": artist}
            tmp = WikiSongCollection(self._uri_path, self._client, disco_entry=disco_entry)
            packages.append(tmp)
        return packages


class WikiAlbum(WikiSongCollection):
    _category = "album"

    @cached_property
    def num_and_type(self):
        base = super().num_and_type
        return '{} Repackage'.format(base) if self.repackage_of else base

    @cached_property
    def repackaged_version(self):
        href = self._album_info.get("repackage_href")
        if href:
            return WikiAlbum(href)
        return None

    @cached_property
    def repackage_of(self):
        href = self._album_info.get("repackage_of_href")
        if href:
            return WikiAlbum(href)
        return None


class WikiSoundtrack(WikiSongCollection):
    _category = "soundtrack"

    def __init__(self, uri_path=None, client=None, **kwargs):
        super().__init__(uri_path, client, **kwargs)
        if isinstance(self._client, DramaWikiClient):
            self._track_lists = parse_ost_page(self._uri_path, self._clean_soup)
            self._album_info = {
                "track_lists": self._track_lists, "num": None, "type": "OST", "repackage": False, "length": None,
                "released": None, "links": []
            }
            part_1 = self._track_lists[0]
            eng, cjk = part_1["info"]["title"]
            ost_name_rx = re.compile("^(.* OST)\s*-?\s*((?:part|code no)\.?\s*\d+)$", re.IGNORECASE)
            # Note: 'Code No. 1' is a one-off case for 'Spy OST'
            try:
                self.english_name, self.cjk_name = (ost_name_rx.match(val).group(1).strip() for val in (eng, cjk))
            except Exception as e:
                raise WikiEntityInitException("Unexpected OST name for {}".format(self._uri_path)) from e
            self.name = multi_lang_name(self.english_name, self.cjk_name)

            m = ost_name_rx.match(self._discography_entry.get("title", ""))
            if m:
                self._intended = m.group(2).strip(), None

    @cached_property
    def _artists(self):
        if not isinstance(self._client, DramaWikiClient):
            return super()._artists

        artists = []
        for track_section in self._track_lists:
            for _artist in track_section["info"]["artist"]:
                eng, cjk = _artist["artist"]
                try:
                    group_eng, group_cjk = _artist["of_group"]
                except KeyError:
                    group_eng, group_cjk = None, None
                artists.append((eng, cjk, group_eng, group_cjk))
        return artists

    @cached_property
    def artists(self):
        if not isinstance(self._client, DramaWikiClient):
            return super().artists

        artists = set()
        for eng, cjk, group_eng, group_cjk in self._artists:
            if eng.lower() == "various artists":
                continue
            try:
                artist = WikiArtist(name=eng)
            except AmbiguousEntityException as e:
                if not group_eng:
                    fmt = "{}'s artist={!r} is ambiguous"
                    if e.alternatives:
                        fmt += " - it could be one of: {}".format(" | ".join(e.alternatives))
                    log.warning(fmt.format(self, eng), extra={"color": (11, 9)})
                    artists.add(WikiArtist(name=eng, no_fetch=True))
                    continue

                for alt_href in e.alternatives:
                    tmp_artist = WikiArtist(alt_href)
                    try:
                        if isinstance(tmp_artist, WikiSinger) and tmp_artist.member_of.english_name == group_eng:
                            artists.add(tmp_artist)
                            break
                    except AttributeError:
                        pass
                else:
                    fmt = "{}'s artist={!r} is ambiguous"
                    if e.alternatives:
                        fmt += " - it could be one of: {}".format(" | ".join(e.alternatives))
                    log.warning(fmt.format(self, eng), extra={"color": (11, 9)})
                    artists.add(WikiArtist(name=eng, no_fetch=True))
            except CodeBasedRestException as e:
                fmt = "Error retrieving info for {}'s artist={!r}: {}"
                log.error(fmt.format(self, eng, e), extra={"color": 13})
                artists.add(WikiArtist(name=eng, no_fetch=True))
            else:
                artists.add(artist)
        return sorted(artists)


class WikiFeatureOrSingle(WikiSongCollection):
    _category = "collab/feature/single"

    def _get_tracks(self, edition_or_part=None, disk=None):
        if self._raw and self._track_lists:
            log.log(9, "Skipping WikiFeatureOrSingle _get_tracks()")
            return super()._get_tracks(edition_or_part)

        track_info = self._discography_entry.get("track_info")
        if track_info:
            single = track_info.copy()
            collabs = set(single.get("collaborators") or [])
            collabs.update(c["artist"][0] for c in self._discography_entry.get("collaborators", []))
            single["collaborators"] = sorted(collabs)
            misc = single.get("misc") or []
            if self._info:
                misc.extend(self._info)
            single["misc"] = misc
        else:
            single = {
                "name_parts": (self.english_name, self.cjk_name), "num": 1,
                # "collaborators": list(self._discography_entry.get("collaborators", {}))
                "collaborators": [c["artist"][0] for c in self._discography_entry.get("collaborators", [])],
                "misc": self._info
            }
        return {"tracks": [single]}


class WikiTrack(DictAttrPropertyMixin):
    disk = DictAttrProperty("_info", "disk", type=int, default=1)
    num = DictAttrProperty("_info", "num", type=lambda x: x if x is None else int(x), default=None)
    length_str = DictAttrProperty("_info", "length", default="-1:00")
    language = DictAttrProperty("_info", "language", default=None)
    version = DictAttrProperty("_info", "version", default=None)
    misc = DictAttrProperty("_info", "misc", default=None)
    from_ost = DictAttrProperty("_info", "from_ost", default=False)
    from_compilation = DictAttrProperty("_info", "compilation", default=False)
    _collaborators = DictAttrProperty("_info", "collaborators", default_factory=list)
    _artist = DictAttrProperty("_info", "artist", default=None)

    def __init__(self, info, collection, artist_context):
        self._info = info   # num, length, language, version, name_parts, collaborators, misc, artist
        self._artist_context = artist_context
        self._collection = collection
        self.english_name, self.cjk_name = self._info["name_parts"]
        self.name = multi_lang_name(self.english_name, self.cjk_name)

        if self.from_ost and self._artist_context:
            # log.debug("Comparing collabs={} to aliases={}".format(self._collaborators, self._artist_context.aliases))
            if not any(lc_alias in self._lc_collaborator_map for lc_alias in self._artist_context.lc_aliases):
                self._artist_context = None
            else:
                for lc_alias in self._artist_context.lc_aliases:
                    try:
                        collab_name = self._lc_collaborator_map[lc_alias]
                    except KeyError:
                        pass
                    else:
                        try:
                            self._collaborators.remove(collab_name)
                        except ValueError:
                            pass
        else:
            # Clean up the collaborator list for tracks that include the primary artist in the list of collaborators
            # Example case: LOONA pre-debut single albums
            if self._collaborators:
                if self._artist and self._artist.lower() in self._lc_collaborator_map:
                    self._collaborators.remove(self._lc_collaborator_map[self._artist.lower()])
                elif self._collection:
                    for artist in self._collection.artists:
                        for lc_alias in artist.lc_aliases:
                            try:
                                collab_name = self._lc_collaborator_map[lc_alias]
                            except KeyError:
                                pass
                            else:
                                try:
                                    self._collaborators.remove(collab_name)
                                except ValueError:
                                    pass

    def __repr__(self):
        if self.num is not None:
            name = "{}[{:2d}][{!r}]".format(type(self).__name__, self.num, self.name)
        else:
            name = "{}[??][{!r}]".format(type(self).__name__, self.name)
        len_str = "[{}]".format(self.length_str) if self.length_str != "-1:00" else ""
        return "<{}{}{}>".format(name, "".join(self._formatted_name_parts), len_str)

    @cached_property
    def _lc_collaborator_map(self):
        return {collab.lower(): collab for collab in self._collaborators}

    @property
    def _cmp_attrs(self):
        return self._collection, self.disk, self.num, self.long_name

    def __lt__(self, other):
        comparison_type_check(self, other, WikiTrack, "<")
        return self._cmp_attrs < other._cmp_attrs

    def __gt__(self, other):
        comparison_type_check(self, other, WikiTrack, ">")
        return self._cmp_attrs > other._cmp_attrs

    @cached_property
    def _formatted_name_parts(self):
        parts = []
        if self.version:
            parts.append("{} ver.".format(self.version) if not self.version.lower().startswith("inst") else self.version)
        if self.language:
            parts.append("{} ver.".format(self.language))
        if self.misc:
            parts.extend(self.misc)
        if self._artist:
            artist_aliases = set(chain.from_iterable(artist.aliases for artist in self._collection.artists))
            if self._artist not in artist_aliases:
                parts.append("{} solo".format(self._artist))
        if self._collaborators:
            collabs = ", ".join(self._collaborators)
            if self.from_compilation or (self.from_ost and self._artist_context is None):
                parts.insert(0, "by {}".format(collabs))
            else:
                parts.append("with {}".format(collabs))
        return tuple(map("({})".format, parts))

    @cached_property
    def long_name(self):
        return " ".join(chain((self.name,), self._formatted_name_parts))

    @property
    def seconds(self):
        m, s = map(int, self.length_str.split(":"))
        return (s + (m * 60)) if m > -1 else 0

    def expected_filename(self, ext='mp3'):
        base = '{}.{}'.format(self.long_name, ext)
        return '{:02d}. {}'.format(self.num, base) if self.num else base

    def expected_rel_path(self, ext='mp3'):
        return self._collection.expected_rel_path.joinpath(self.expected_filename(ext))


def find_ost(artist, title, disco_entry):
    b_client = WikiClient()
    d_client = DramaWikiClient()
    k_client = KpopWikiClient()
    w_client = WikipediaClient()
    show_title = " ".join(title.split()[:-1])  # Search without 'OST' suffix
    # log.debug("{}: Searching for show {!r} for OST {!r}".format(artist, show_title, title))

    for client in (d_client, w_client):
        alt_match = client.title_search(show_title)
        if alt_match:
            series = WikiTVSeries(alt_match, client)
            if series.ost_href:
                return WikiSongCollection(series.ost_href, d_client, disco_entry=disco_entry, artist_context=artist)

            for alt_title in series.aka:
                # log.debug("Found AKA for {!r}: {!r}".format(show_title, alt_title))
                alt_uri_path = d_client.normalize_name(alt_title + " OST")
                if alt_uri_path:
                    log.debug("Found alternate uri_path for {!r}: {!r}".format(title, alt_uri_path))
                    return WikiSongCollection(alt_uri_path, d_client, disco_entry=disco_entry, artist_context=artist)

    if artist._disco_page:
        # log.debug("{}: Processing discography page to find OST tracks...".format(artist))
        title_rx = synonym_pattern(title)
        for ost_name, tracks in artist._disco_page._soundtracks.items():
            if title_rx.match(ost_name):
                # log.debug("{}: Found discography page match {!r} = {!r}".format(artist, title, ost_name))
                album_info = {
                    "track_lists": [{"section": None, "tracks": tracks}], "num": None, "type": "OST",
                    "repackage": False, "length": None, "released": None, "links": []
                }
                _entry = disco_entry.copy()
                _entry["uri_path"] = None
                return WikiSoundtrack(
                    None, b_client, no_type_check=True, disco_entry=_entry, album_info=album_info, artist_context=artist
                )

    if disco_entry.get("wiki") == k_client._site and disco_entry.get("uri_path"):
        return WikiSoundtrack(disco_entry["uri_path"], k_client, disco_entry=disco_entry, artist_context=artist)

    return None
