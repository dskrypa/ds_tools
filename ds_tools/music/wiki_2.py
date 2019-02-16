#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
:author: Doug Skrypa
"""

import json
import logging
import os
import re
import string
from contextlib import suppress
from itertools import chain
from pathlib import Path
from urllib.parse import urlparse

import bs4
from fuzzywuzzy import fuzz, utils as fuzz_utils

from ..utils import (
    soupify, cached_property, datetime_with_tz, now, UnexpectedTokenError, format_duration,
    ParentheticalParser, is_any_cjk, contains_any_cjk, CacheKey, flatten_mapping
)
from .exceptions import *
from .utils import *
from .wiki_rest import WikiClient, KpopWikiClient, WikipediaClient

__all__ = []
log = logging.getLogger("ds_tools.music.wiki_2")

ALBUM_DATED_TYPES = ("Singles", )
ALBUM_MULTI_DISK_TYPES = ("Albums", "Special Albums", "Japanese Albums", "Remake Albums", "Repackage Albums")
ALBUM_NUMBERED_TYPES = (
    "Albums", "Mini Albums", "Special Albums", "Japanese Albums", "Japanese Mini Albums", "Single Albums",
    "Remake Albums", "Repackage Albums", "Summer Mini Albums"
)
ALBUM_TYPE_MAP = {
    "mini_album": "Mini Album", "single": "Single", "digital_single": "Single", "special_single": "Single",
    "single_album": "Single Album", "studio_album": "Album", "collaboration": "Collaboration",
    "promotional_single": "Single", "special_album": "Special Album", "ost": "Soundtrack",
    "feature": "Collaboration", "best_album": "Compilation", "live_album": "Live", "other_release": "Other",
    "collaborations_and_feature": "Collaboration", "collaboration_single": "Collaboration",
    "remake_album": "Remake Album", # Album that contains only covers of other artists' songs
    "repackage_album": "Repackage Album"
}
JUNK_CHARS = string.whitespace + string.punctuation
NUM_STRIP_TBL = str.maketrans({c: "" for c in "0123456789"})
NUMS = {
    "first": "1st", "second": "2nd", "third": "3rd", "fourth": "4th", "fifth": "5th", "sixth": "6th",
    "seventh": "7th", "eighth": "8th", "ninth": "9th", "tenth": "10th", "debut": "1st"
}
STRIP_TBL = str.maketrans({c: "" for c in JUNK_CHARS})


def sanitize_dict(a_dict):
    a_dict = flatten_mapping(a_dict)
    return {key: tuple(value) if isinstance(value, list) else value for key, value in a_dict.items()}


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

    def __call__(cls, uri_path=None, client=None, *, name=None, disco_entry=None, **kwargs):
        disco_entry = disco_entry or {}
        if client is None:
            if uri_path and uri_path.startswith(("http://", "https://")):
                _url = urlparse(uri_path)
                client = WikiClient.for_site(_url.hostname)
                uri_path = _url.path[6:] if _url.path.startswith("/wiki/") else _url.path
            else:
                client = KpopWikiClient()

        if name and not uri_path:
            uri_path = client.normalize_name(name)
        elif name and uri_path and uri_path.startswith("//"):
            uri_path = None

        is_feature = disco_entry and disco_entry.get("base_type") == "features"
        if uri_path or is_feature:
            if uri_path and " " in uri_path:
                uri_path = client.normalize_name(uri_path)

            key = CacheKey.simple(uri_path, client, name, **sanitize_dict(disco_entry))
            if key in WikiEntityMeta._instances:
                inst = WikiEntityMeta._instances[key]
                # noinspection PyUnresolvedReferences
                if cls._category and ((inst._category == cls._category) or (inst._category in cls._category)):
                    return inst

            # noinspection PyUnresolvedReferences
            cls_cat = cls._category
            if not uri_path and (disco_entry and disco_entry.get("base_type") == "features"):
                category = "feature"
                url, raw = None, None
            else:
                url = client.url_for(uri_path)
                # log.debug("Using url: {}".format(url))
                # Note: client.get_entity_base caches args->return vals
                raw, cats = client.get_entity_base(uri_path, cls_cat.title() if isinstance(cls_cat, str) else None)
                if any(i in cat for i in ("albums", "discography article stubs", "singles") for cat in cats):
                    category = "album"
                elif any(i in cat for i in ("groups", "group article stubs") for cat in cats):
                    category = "group"
                elif any(i in cat for i in ("singers", "person article stubs") for cat in cats):
                    category = "singer"
                elif any(i in cat for i in ("osts",) for cat in cats):
                    category = "soundtrack"
                else:
                    log.debug("Unable to determine category for {}".format(url))
                    category = None

            exp_cls = WikiEntityMeta._category_classes.get(category)
            exp_base = WikiEntityMeta._category_bases.get(category)
            if (exp_cls and not issubclass(exp_cls, cls)) and (exp_base and not issubclass(exp_base, cls)):
                article = "an" if category and category[0] in "aeiou" else "a"
                raise TypeError("{} is {} {} page (expected: {})".format(url, article, category, cls_cat))
        else:
            exp_cls = cls
            raw = None
            key = CacheKey.simple(uri_path, client, name, **sanitize_dict(disco_entry))

        if key not in WikiEntityMeta._instances:
            obj = exp_cls.__new__(exp_cls, uri_path, client)
            # noinspection PyArgumentList
            obj.__init__(uri_path, client, name=name, raw=raw, disco_entry=disco_entry, **kwargs)
            WikiEntityMeta._instances[key] = obj
        return WikiEntityMeta._instances[key]


class WikiEntity(metaclass=WikiEntityMeta):
    __instances = {}
    _categories = {}
    _category = None

    def __init__(self, uri_path=None, client=None, *, name=None, raw=None, **kwargs):
        self._client = client
        self._uri_path = uri_path
        self._raw = raw if raw is not None else client.get_page(uri_path) if uri_path else None
        self.name = name or uri_path
        self.aliases = [self.name]

    def __repr__(self):
        return "<{}({!r})>".format(type(self).__name__, self.name)

    def __eq__(self, other):
        if not isinstance(other, WikiEntity):
            return False
        return self.name == other.name and self._raw == other._raw

    def __hash__(self):
        return hash((self.name, self._raw))

    @property
    def _soup(self):
        # soupify every time so that elements may be modified/removed without affecting other functions
        return soupify(self._raw) if self._raw else None

    @cached_property
    def _aside(self):
        """The parsed 'aside' section of this page"""
        if not hasattr(self, "_WikiEntity__aside"):
            _ = self._clean_soup
        return parse_aside(self.__aside) if self.__aside else {}

    @cached_property
    def _clean_soup(self):
        """The soupified page content, with the undesirable parts at the beginning removed"""
        try:
            content = self._soup.find("div", id="mw-content-text")
        except AttributeError as e:
            self.__aside = None
            log.warning(e)
            return None

        aside = content.find("aside")
        self.__aside = aside.extract() if aside else None

        for ele_name in ("center",):
            rm_ele = content.find(ele_name)
            if rm_ele:
                rm_ele.extract()

        for clz in ("dablink", "hatnote", "shortdescription", "infobox"):
            rm_ele = content.find(class_=clz)
            if rm_ele:
                rm_ele.extract()

        for rm_ele in content.find_all(class_="mw-empty-elt"):
            rm_ele.extract()

        first_ele = content.next_element
        if getattr(first_ele, "name", None) == "dl":
            first_ele.extract()

        return content


class WikiArtist(WikiEntity):
    _category = ("group", "singer")
    _known_artists = set()
    __known_artists_loaded = False

    def __init__(self, uri_path=None, client=None, *, name=None, strict=True, **kwargs):
        super().__init__(uri_path, client, **kwargs)
        self.english_name, self.cjk_name, self.stylized_name, self.aka = None, None, None, None
        if self._raw:
            try:
                self.english_name, self.cjk_name, self.stylized_name, self.aka = parse_intro_name(self._clean_soup.text)
            except Exception as e:
                if strict:
                    raise e
                log.warning("{} while processing intro for {}: {}".format(type(e).__name__, name or uri_path, e))
        if name and not any(val for val in (self.english_name, self.cjk_name, self.stylized_name)):
            self.english_name, self.cjk_name = split_name(name)

        if self.english_name and self.cjk_name:
            self.name = "{} ({})".format(self.english_name, self.cjk_name)
        else:
            self.name = self.english_name or self.cjk_name

        self.aliases = [a for a in (self.english_name, self.cjk_name, self.stylized_name, self.aka, self.name) if a]
        if self.english_name and isinstance(self._client, KpopWikiClient):
            type(self)._known_artists.add(self.english_name.lower())

    def __repr__(self):
        try:
            return "<{}({!r})>".format(type(self).__name__, self.stylized_name or self.name)
        except AttributeError as e:
            return "<{}({!r})>".format(type(self).__name__, self._uri_path)

    def __lt__(self, other):
        if not isinstance(other, (WikiArtist, str)):
            fmt = "'<' not supported between instances of {!r} and {!r}"
            raise TypeError(fmt.format(type(self).__name__, type(other).__name__))
        return (self.name < other.name) if isinstance(other, WikiArtist) else (self.name < other)

    def __gt__(self, other):
        if not isinstance(other, (WikiArtist, str)):
            fmt = "'>' not supported between instances of {!r} and {!r}"
            raise TypeError(fmt.format(type(self).__name__, type(other).__name__))
        return (self.name > other.name) if isinstance(other, WikiArtist) else (self.name > other)

    @classmethod
    def known_artist_eng_names(cls):
        if not cls.__known_artists_loaded:
            cls.__known_artists_loaded = True
            known_artists_path = Path(__file__).resolve().parents[2].joinpath("music/artist_dir_to_artist.json")
            with open(known_artists_path.as_posix(), "r", encoding="utf-8") as f:
                artists = json.load(f)
            cls._known_artists.update((split_name(artist)[0].lower() for artist in artists.values()))
            # cls._known_artists.update(map(str.lower, artists.keys()))
        return cls._known_artists

    @classmethod
    def known_artists(cls):
        for name in sorted(cls.known_artist_eng_names()):
            yield WikiArtist(name=name)

    @property
    def _discography(self):
        try:
            discography_h2 = self._soup.find("span", id="Discography").parent
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
                while li_eles:
                    li = li_eles.pop(0)
                    ul = li.find("ul")
                    if ul:
                        ul.extract()                            # remove nested list from tree
                        li_eles = list(ul.children) + li_eles   # insert elements from the nested list at top

                    entry = parse_discography_entry(self, li, album_type, lang)
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
            try:
                obj = WikiSongCollection(entry["uri_path"], WikiClient.for_site(entry["wiki"]), disco_entry=entry)
                discography.append(obj)
            except MusicException as e:
                fmt = "{}: Error processing discography entry for {!r} / {!r}: {}"
                log.error(fmt.format(self, entry["uri_path"], entry["title"], e), extra={"color": 13})
                raise e

        return discography


class WikiGroup(WikiArtist):
    _category = "group"

    def __init__(self, uri_path=None, client=None, **kwargs):
        super().__init__(uri_path, client, **kwargs)
        self.subunit_of = None

        clean_soup = self._clean_soup
        if re.search("^.* is (?:a|the) .*?sub-?unit of .*?group", clean_soup.text.strip()):
            for i, a in enumerate(clean_soup.find_all("a")):
                try:
                    href = a.get("href")[6:]
                except TypeError as e:
                    href = None
                if href and (href != self._uri_path):
                    self.subunit_of = WikiGroup(href)
                    break

    @cached_property
    def members(self):
        content = self._soup.find("div", id="mw-content-text")
        members_h2 = content.find("span", id="Members").parent
        members_container = members_h2.next_sibling.next_sibling
        members = []
        if members_container.name == "ul":
            for li in members_container:
                a = li.find("a")
                if a:
                    members.append(WikiSinger(a.get("href")[6:]))
                else:
                    m = re.match("(.*?)\s*-\s*(.*)", li.text)
                    member = list(map(str.strip, m.groups()))[0]
                    members.append(member)
        elif members_container.name == "table":
            for tr in members_container.find_all("tr"):
                if tr.find("th"):
                    continue
                a = tr.find("a")
                if a:
                    members.append(WikiSinger(a.get("href")[6:]))
                else:
                    member = list(map(str.strip, (td.text.strip() for td in tr.find_all("td"))))[0]
                    members.append(member)
        return members

    @cached_property
    def sub_units(self):
        content = self._soup.find("div", id="mw-content-text")
        su_ele = content.find(id=re.compile("sub[-_]?units", re.IGNORECASE))
        if not su_ele:
            return []
        sub_units = []
        while su_ele and not su_ele.name.startswith("h"):
            su_ele = su_ele.parent
        ul = su_ele.next_sibling.next_sibling
        if not ul or ul.name != "ul":
            raise RuntimeError("Unexpected sibling element for sub-units")

        for li in ul.find_all("li"):
            a = li.find("a")
            if a and a.get("href"):
                sub_units.append(WikiGroup(a.get("href")[6:]))
        return sub_units


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
                group_name_text = mem_match.group(2)
                for i, a in enumerate(clean_soup.find_all("a")):
                    if a.text in group_name_text:
                        try:
                            href = a.get("href")[6:]
                        except TypeError as e:
                            href = None
                        if href and (href != self._uri_path):
                            self.member_of = WikiGroup(href)
                            break


class WikiSongCollection(WikiEntity):
    _category = ("album", "soundtrack", "feature")

    def __init__(self, uri_path=None, client=None, *, disco_entry=None, **kwargs):
        super().__init__(uri_path, client, **kwargs)
        self._discography_entry = disco_entry or {}
        self.english_name, self.cjk_name, self.stylized_name, self.aka = None, None, None, None
        self._album_info = {}
        if self._raw:
            albums = parse_album_page(self._clean_soup, self._aside)
            if len(albums) > 1:
                err_base = "{} contains both original+repackaged album info on the same page".format(uri_path)
                if not disco_entry:
                    msg = "{} - a discography entry is required to identify it".format(err_base)
                    raise WikiEntityIdentificationException(msg)
                d_title = disco_entry.get("title")
                for album in albums:
                    if d_title in album["title_parts"]:
                        self._album_info = album
                        break
                else:
                    msg = "{}, and it could not be matched with a discography entry".format(err_base)
                    raise WikiEntityIdentificationException(msg)
            else:
                self._album_info = albums[0]

            self.english_name, self.cjk_name, self.stylized_name, self.aka = self._album_info["title_parts"]
        elif disco_entry:
            try:
                self.english_name, self.cjk_name = eng_cjk_sort(disco_entry["title"])
            except Exception as e:
                msg = "Unable to find valid title in discography entry: {}".format(disco_entry)
                raise WikiEntityInitException(msg) from e
        else:
            msg = "A valid uri_path / discography entry are required to initialize a {}".format(type(self).__name__)
            raise WikiEntityInitException(msg)

        if self.english_name and self.cjk_name:
            self.name = "{} ({})".format(self.english_name, self.cjk_name)
        else:
            self.name = self.english_name or self.cjk_name

    @cached_property
    def _artists(self):
        d_artist = self._discography_entry.get("primary_artist")
        artists = {d_artist[0].lower(): d_artist[1]} if d_artist else {}

        d_collabs = self._discography_entry.get("collaborators", {})
        a_artists = self._album_info.get("artists", {})
        for artist, href in chain(d_collabs.items(), a_artists.items()):
            if href:
                if href.startswith("/wiki"):
                    href = href[6:]
            artist = artist.lower()
            if not artists.get(artist):
                artists[artist] = href

        return artists

    @cached_property
    def artists(self):
        return sorted({WikiArtist(href, name=name) for name, href in self._artists.items()})

    @cached_property
    def artist(self):
        d_artist = self._discography_entry.get("primary_artist")
        if d_artist:
            return WikiArtist(d_artist[1], name=d_artist[0])

        artists = self.artists
        if len(artists) == 1:
            return artists[0]
        raise AttributeError("{} has multiple contributing artists".format(self))


class WikiAlbum(WikiSongCollection):
    _category = "album"

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


class WikiFeatureSingle(WikiSongCollection):
    _category = "feature"




if __name__ == "__main__":
    from ds_tools.logging import LogManager
    lm = LogManager.create_default_logger(2, log_path=None, entry_fmt="%(asctime)s %(name)s %(message)s")
