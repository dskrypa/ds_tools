#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
:author: Doug Skrypa
"""

import json
import logging
import re
import string
from collections import defaultdict
from contextlib import suppress
from itertools import chain
from pathlib import Path
from urllib.parse import urlparse

import bs4
from fuzzywuzzy import fuzz, utils as fuzz_utils

from ..utils import soupify, cached_property, DictAttrPropertyMixin, DictAttrProperty, cached
from .exceptions import *
from .utils import *
from .wiki_rest import WikiClient, KpopWikiClient, WikipediaClient, DramaWikiClient

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

    def __call__(cls, uri_path=None, client=None, *, name=None, disco_entry=None, no_type_check=False, **kwargs):
        """
        :param str|None uri_path: The uri path for a page on a wiki
        :param WikiClient|None client: The WikiClient object to use to retrieve the wiki page
        :param str|None name: The name of a WikiEntity to lookup if the uri_path is unknown
        :param dict|None disco_entry: A dict containing information about an album from an Artist's discography section
        :param bool no_type_check: Skip type checks and do not cache the returned object
        :param kwargs: Additional keyword arguments to pass to the WikiEntity when initializing it
        :return WikiEntity: A WikiEntity (or subclass thereof) based on the provided information
        """
        if disco_entry:
            uri_path = uri_path or disco_entry.get("uri_path")
            name = name or disco_entry.get("title")
            disco_site = disco_entry.get("wiki")
            if disco_site and not client:
                client = WikiClient.for_site(disco_site)
        else:
            if name and not uri_path:
                if client is None:
                    client = KpopWikiClient()
                uri_path = client.normalize_name(name)
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

        if no_type_check:
            obj = cls.__new__(cls, uri_path, client)
            # noinspection PyArgumentList
            obj.__init__(uri_path, client, name=name, disco_entry=disco_entry, **kwargs)
            return obj

        is_feat_collab = disco_entry and disco_entry.get("base_type") in ("features", "collaborations", "singles")
        if uri_path or is_feat_collab:
            if uri_path and " " in uri_path:
                uri_path = client.normalize_name(uri_path)

            key = (uri_path, client, name)
            if key in WikiEntityMeta._instances:
                inst = WikiEntityMeta._instances[key]
                # noinspection PyUnresolvedReferences
                if cls._category and ((inst._category == cls._category) or (inst._category in cls._category)):
                    return inst

            # noinspection PyUnresolvedReferences
            cls_cat = cls._category
            if not uri_path and is_feat_collab:
                category = "collab/feature/single"
                url, raw = None, None
            else:
                url = client.url_for(uri_path)
                # log.debug("Using url: {}".format(url))
                # Note: client.get_entity_base caches args->return vals
                raw, cats = client.get_entity_base(uri_path, cls_cat.title() if isinstance(cls_cat, str) else None)
                if any(i in cat for i in ("albums", "discography article stubs", "singles", "songs") for cat in cats):
                    category = "album"
                elif any(i in cat for i in ("groups", "group article stubs") for cat in cats):
                    category = "group"
                elif any(i in cat for i in ("singers", "person article stubs") for cat in cats):
                    category = "singer"
                elif any(i in cat for i in ("osts", "kost", "jost", "cost") for cat in cats):
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
            key = (uri_path, client, name)

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
    def _side_info(self):
        """The parsed 'aside' / 'infobox' section of this page"""
        if not hasattr(self, "_WikiEntity__side_info"):
            _ = self._clean_soup

        return {} if not self.__side_info else self._client.parse_side_info(self.__side_info)

    @cached_property
    def _clean_soup(self):
        """The soupified page content, with the undesirable parts at the beginning removed"""
        try:
            content = self._soup.find("div", id="mw-content-text")
        except AttributeError as e:
            self.__side_info = None
            log.warning(e)
            return None

        if isinstance(self._client, KpopWikiClient):
            aside = content.find("aside")
            self.__side_info = aside.extract() if aside else None

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

            infobox = content.find("table", class_=re.compile("infobox vevent.*"))
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

        self.name = multi_lang_name(self.english_name, self.cjk_name)
        self.aliases = [a for a in (self.english_name, self.cjk_name, self.stylized_name, self.aka, self.name) if a]
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
            known_artists_path = Path(__file__).resolve().parents[2].joinpath("music/artist_dir_to_artist.json")
            with open(known_artists_path.as_posix(), "r", encoding="utf-8") as f:
                artists = json.load(f)
            cls._known_artists.update((split_name(artist)[0].lower() for artist in artists.values()))
        return cls._known_artists

    @classmethod
    def known_artists(cls):
        for name in sorted(cls.known_artist_eng_names()):
            yield WikiArtist(name=name)

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
                m = re.match("^(.*)\s+Part.\d+$", title, re.IGNORECASE)
                if m:
                    title = m.group(1).strip()
                uri_path = client.normalize_name(title)
            else:
                client = WikiClient.for_site(entry["wiki"])
                uri_path = entry["uri_path"]

            try:
                discography.append(WikiSongCollection(uri_path, client, disco_entry=entry))
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
                href = a.get("href") or ""
                href = href[6:] if href.startswith("/wiki/") else href
                if href and (href != self._uri_path):
                    self.subunit_of = WikiGroup(href)
                    break

    @cached_property
    def members(self):
        members_h2 = self._clean_soup.find("span", id="Members").parent
        members_container = members_h2.next_sibling.next_sibling
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
    _category = ("album", "soundtrack", "collab/feature/single")

    def __init__(self, uri_path=None, client=None, *, disco_entry=None, **kwargs):
        super().__init__(uri_path, client, **kwargs)
        self._discography_entry = disco_entry or {}
        self.english_name, self.cjk_name, self.stylized_name, self.aka = None, None, None, None
        self._album_info = {}
        self._albums = []
        self._primary_artist = None
        self._intended = None
        if isinstance(self._client, DramaWikiClient):
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

            self.english_name, self.cjk_name, self.stylized_name, self.aka = self._album_info["title_parts"]
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
            self._track_lists = [self._album_info.get("tracks")]

        self.name = multi_lang_name(self.english_name, self.cjk_name)

    def __lt__(self, other):
        comparison_type_check(self, other, WikiSongCollection, "<")
        return self.name < other.name

    def __gt__(self, other):
        comparison_type_check(self, other, WikiSongCollection, ">")
        return self.name > other.name

    @cached_property
    def album_type(self):
        return self._album_info.get("type") or self._discography_entry.get("base_type")

    @cached_property
    def _artists(self):
        """dict(artist.lower(): uri_path)"""
        artists = {self._primary_artist[0].lower(): self._primary_artist[1]} if self._primary_artist else {}
        d_collabs = self._discography_entry.get("collaborators", {})
        a_artists = self._album_info.get("artists", {})
        for artist, href in chain(d_collabs.items(), a_artists.items()):
            artist = artist.lower()
            if not artists.get(artist):
                artists[artist] = href[6:] if href and href.startswith("/wiki/") else href
        return artists

    @cached_property
    def artists(self):
        return sorted({WikiArtist(href, name=name) for name, href in self._artists.items()})

    @cached_property
    def artist(self):
        if self._primary_artist:
            return WikiArtist(self._primary_artist[1], name=self._primary_artist[0])

        artists = self.artists
        if len(artists) == 1:
            return artists[0]
        raise AttributeError("{} has multiple contributing artists".format(self))

    @cached_property
    def _editions_by_disk(self):
        editions_by_disk = defaultdict(list)
        for track_section in self._track_lists:
            editions_by_disk[track_section.get("disk")].append(track_section)
        return editions_by_disk

    def _get_tracks(self, edition_or_part=None, disk=None):
        if self._raw:
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
            is_part = lc_ed_or_part.startswith("part")
            part_rx = re.compile("part\.?\s*")
            if is_part:
                lc_ed_or_part = part_rx.sub("part ", lc_ed_or_part)

            bonus_match = None
            bonus_rx = re.compile("^(.*)\s+bonus tracks?$", re.IGNORECASE)
            for i, edition in enumerate(editions):
                name = (edition.get("section") or "").lower()
                if name == lc_ed_or_part or (is_part and lc_ed_or_part in part_rx.sub("part ", name)):
                    return edition
                else:
                    m = bonus_rx.match(name)
                    if m and m.group(1).strip() == lc_ed_or_part:
                        bonus_match = i
                        # log.debug("bonus_match={}: {}".format(bonus_match, edition))
                        break

            if bonus_match is not None:
                edition = editions[bonus_match]
                first_track = min(t["num"] for t in edition["tracks"])
                if first_track == 1:
                    return edition
                name = bonus_rx.match(edition["section"]).group(1).strip()
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
                log.debug("No page content found for {} - returning empty track list".format(self))
                return {"tracks": []}

    @cached(True)
    def get_tracks(self, edition_or_part=None, disk=None):
        if self._intended is not None and edition_or_part is None and disk is None:
            if len(self._intended) == 3:
                return [WikiTrack(self._intended[2]._info, self)]
            elif len(self._intended) == 2:
                # noinspection PyTupleAssignmentBalance
                edition_or_part, disk = self._intended
        _tracks = self._get_tracks(edition_or_part, disk)
        return [WikiTrack(info, self) for info in _tracks["tracks"]]

    @cached_property
    def editions_and_disks(self):
        bonus_rx = re.compile("^(.*)\s+bonus tracks?$", re.IGNORECASE)
        editions = []
        for edition in self._track_lists:
            section = edition.get("section")
            m = bonus_rx.match(section or "")
            name = m.group(1).strip() if m else section
            disk = edition.get("disk", 1)
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
            if not all(val.lower().endswith(("part 1", "part.1")) for val in (eng, cjk)):
                raise WikiEntityInitException("Unexpected OST name for {}".format(self._uri_path))

            self.english_name, self.cjk_name = eng[:-6].strip(), cjk[:-6].strip()
            self.name = multi_lang_name(self.english_name, self.cjk_name)
            # self._part = None
            if "part" in self._discography_entry.get("title", "").lower():
                # self._intended = self._discography_entry.get("title"), None
                m = re.match("^.*\s+(Part.\d+)$", self._discography_entry["title"], re.IGNORECASE)
                if m:
                    self._intended = m.group(1).strip(), None

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
                    raise e
                for alt_href in e.alternatives:
                    tmp_artist = WikiArtist(alt_href)
                    try:
                        if isinstance(tmp_artist, WikiSinger) and tmp_artist.member_of.english_name == group_eng:
                            artists.add(tmp_artist)
                            break
                    except AttributeError:
                        pass
                else:
                    raise e
            else:
                artists.add(artist)
        return sorted(artists)

    # def _get_tracks(self, edition_or_part=None, disk=1):
    #     return super()._get_tracks(edition_or_part or self._part)


class WikiFeatureSingle(WikiSongCollection):
    _category = "collab/feature/single"

    def _get_tracks(self, edition_or_part=None, disk=None):
        if self._raw:
            log.debug("Skipping WikiFeatureSingle _get_tracks()")
            return super()._get_tracks(edition_or_part)

        single = {
            "name_parts": (self.english_name, self.cjk_name), "num": 1,
            "collaborators": list(self._discography_entry.get("collaborators", {}))
        }
        return {"tracks": [single]}


class WikiTrack(DictAttrPropertyMixin):
    disk = DictAttrProperty("_info", "disk", type=int, default=1)
    num = DictAttrProperty("_info", "num", type=lambda x: x if x is None else int(x), default=None)
    length_str = DictAttrProperty("_info", "length", default="-1:00")
    language = DictAttrProperty("_info", "language", default=None)
    version = DictAttrProperty("_info", "version", default=None)
    misc = DictAttrProperty("_info", "misc", default=None)
    _collaborators = DictAttrProperty("_info", "collaborators", default_factory=list)
    _artist = DictAttrProperty("_info", "artist", default=None)

    def __init__(self, info, collection):
        self._info = info   # num, length, language, version, name_parts, collaborators, misc, artist
        self._collection = collection
        self.english_name, self.cjk_name = self._info["name_parts"]
        self.name = multi_lang_name(self.english_name, self.cjk_name)

    def __repr__(self):
        if self.num is not None:
            name = "{}[{:2d}][{!r}]".format(type(self).__name__, self.num, self.name)
        else:
            name = "{}[??][{!r}]".format(type(self).__name__, self.name)
        len_str = "[{}]".format(self.length_str) if self.length_str != "-1:00" else ""
        return "<{}{}{}>".format(name, "".join(self._formatted_name_parts), len_str)

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
            parts.append("{} ver.".format(self.version) if self.version.lower() == "acoustic" else self.version)
        if self.language:
            parts.append("{} ver.".format(self.language))
        if self.misc:
            parts.extend(self.misc)
        if self._collaborators:
            parts.append("with {}".format(", ".join(self._collaborators)))
        return tuple(map("({})".format, parts))

    @cached_property
    def long_name(self):
        return " ".join(chain((self.name,), self._formatted_name_parts))

    @property
    def seconds(self):
        m, s = map(int, self.length_str.split(":"))
        return (s + (m * 60)) if m > -1 else 0


if __name__ == "__main__":
    from ds_tools.logging import LogManager
    lm = LogManager.create_default_logger(2, log_path=None, entry_fmt="%(asctime)s %(name)s %(message)s")