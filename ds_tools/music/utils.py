"""
:author: Doug Skrypa
"""

import logging
import re
import types
from collections import OrderedDict
from enum import Enum
from itertools import chain, combinations
from urllib.parse import urlparse

# import Levenshtein as lev
from bs4.element import NavigableString
from fuzzywuzzy import utils as fuzz_utils

from ..core import datetime_with_tz
from ..utils import (
    is_any_cjk, ParentheticalParser, contains_any_cjk, is_hangul, DASH_CHARS, QMARKS, num_suffix,
    ListBasedRecursiveDescentParser, ALL_WHITESPACE, UnexpectedTokenError
)
from .exceptions import *

__all__ = [
    "sanitize", "unsurround", "_normalize_title", "parse_intro_name", "split_name", "eng_cjk_sort", "categorize_langs",
    "LangCat", "parse_discography_entry", "parse_aside", "parse_album_page", "parse_track_info", "parse_ost_page",
    "parse_wikipedia_album_page", "parse_infobox", "edition_combinations", "multi_lang_name", "comparison_type_check",
    "parse_discography_page", "synonym_pattern", "parse_drama_wiki_info_list"
]
log = logging.getLogger("ds_tools.music.utils")

FEAT_ARTIST_INDICATORS = ("with", "feat.", "feat ", "featuring")
NUM_STRIP_TBL = str.maketrans({c: "" for c in "0123456789"})
NUM2INT = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9}
NUMS = {
    "first": "1st", "second": "2nd", "third": "3rd", "fourth": "4th", "fifth": "5th", "sixth": "6th",
    "seventh": "7th", "eighth": "8th", "ninth": "9th", "tenth": "10th", "debut": "1st"
}
PATH_SANITIZATION_DICT = {c: "" for c in "*;?<>\""}
PATH_SANITIZATION_DICT.update({"/": "_", ":": "-", "\\": "_", "|": "-"})
PATH_SANITIZATION_TABLE = str.maketrans(PATH_SANITIZATION_DICT)
QMARK_STRIP_TBL = str.maketrans({c: "" for c in QMARKS})
SYNONYMS = [{"and": "and", "&": "&", "+": "\\+"}]


class TrackInfoParser(ListBasedRecursiveDescentParser):
    _entry_point = "content"
    _strip = True
    _opener2closer = {"LPAREN": "RPAREN", "LBPAREN": "RBPAREN", "LBRKT": "RBRKT", "QUOTE": "QUOTE", "DASH": "DASH"}
    _nested_fmts = {"LPAREN": "({})", "LBPAREN": "({})", "LBRKT": "[{}]", "QUOTE": "{!r}", "DASH": "({})"}
    _content_tokens = ["TEXT", "WS"] + [v for k, v in _opener2closer.items() if k != v]
    _req_preceders = ["WS"] + list(_opener2closer.values())
    TOKENS = OrderedDict([
        ("QUOTE", "[{}]".format(QMARKS)),
        ("LPAREN", "\("),
        ("RPAREN", "\)"),
        ("LBPAREN", "（"),
        ("RBPAREN", "）"),
        ("LBRKT", "\["),
        ("RBRKT", "\]"),
        ("TIME", "\s*\d+:\d{2}"),
        ("WS", "\s+"),
        ("DASH", "[{}]".format(DASH_CHARS)),
        ("TEXT", "[^\"“()（）\[\]{}-]+".format(ALL_WHITESPACE)),
    ])

    def __init__(self, selective_recombine=True):
        self._selective_recombine = selective_recombine

    def _lookahead_unpaired(self, closer):
        """Find the position of the next closer that does not have a preceding opener in the remaining tokens"""
        openers = {opener for opener, _closer in self._opener2closer.items() if _closer == closer}
        opened = 0
        closed = 0
        for pos, token in self.tokens[self._idx:]:
            if token.type in openers:
                opened += 1
            elif token.type == closer:
                closed += 1
                if closed > opened:
                    return pos
        return -1

    def parenthetical(self, closer="RPAREN"):
        """
        parenthetical ::= ( { text | WS | ( parenthetical ) }* )
        """
        # log.debug("Opening {}".format(closer))
        if not hasattr(self, "_parenthetical_count"):
            self._parenthetical_count = 0
        self._parenthetical_count += 1
        text = ""
        parts = []
        nested = False
        while self.next_tok:
            if self._accept(closer):
                if text:
                    parts.append(text)
                # log.debug("[closing] Closing {}: {}".format(closer, parts))
                return parts, nested, False
            elif self._accept_any(self._opener2closer):
                prev_tok_type = self.prev_tok.type
                tok_type = self.tok.type
                if tok_type == "DASH":
                    # next_dash = self._lookahead("DASH")
                    try:
                        next_dash = self._remaining.index(self.tok.value)
                    except ValueError:
                        next_dash = -1
                    if next_dash == -1 or next_dash > self._lookahead_unpaired(closer):
                        text += self.tok.value
                        continue
                    elif text and not prev_tok_type == "WS" and self._peek("TEXT"):
                        text += self.tok.value
                        continue

                if text:
                    parts.append(text)
                    text = ""

                parentheticals, _nested, unpaired = self.parenthetical(self._opener2closer[tok_type])
                if len(parts) == len(parentheticals) == 1 and self._parenthetical_count > 2:
                    if parts[0].lower().startswith(FEAT_ARTIST_INDICATORS):
                        parts[0] = "{} of {}".format(parts[0].strip(), parentheticals[0])
                    else:
                        parts[0] += self._nested_fmts[tok_type].format(parentheticals[0])
                else:
                    parts.extend(parentheticals)

                nested = True
            else:
                self._advance()
                text += self.tok.value

        if text:
            parts.append(text)
        # log.debug("[no toks] Closing {}: {}".format(closer, parts))
        return parts, nested, True

    def content(self):
        """
        content :: = text { (parenthetical) }* { text }*
        """
        text = ""
        time_part = None
        parts = []
        while self.next_tok:
            if self._accept_any(self._opener2closer):
                tok_type = self.tok.type
                if text and self.prev_tok.type not in self._req_preceders and self._peek("TEXT"):
                    text += self.tok.value
                    continue
                elif tok_type == "QUOTE":
                    if any((c not in self._remaining) and (self._full.count(c) % 2 == 1) for c in QMARKS):
                        log.debug("Unpaired quote found in {!r}".format(self._full))
                        continue
                elif tok_type == "DASH":
                    # log.debug("Found DASH ({!r}={}); remaining: {!r}".format(self.tok.value, ord(self.tok.value), self._remaining))
                    if self._peek("TIME"):
                        if text:
                            parts.append(text)
                            text = ""
                        continue
                    elif self._peek("WS") or self.tok.value not in self._remaining:
                        # log.debug("Appending DASH because WS did not follow it or the value does not occur again")
                        text += self.tok.value
                        continue
                # elif tok_type == "TIME":
                #     if self.prev_tok.type == "DASH":
                #         parts.append(self.tok.value.strip())
                #     else:
                #         text += self.tok.value
                #         continue

                if text:
                    parts.append(text)
                    text = ""
                parentheticals, nested, unpaired = self.parenthetical(self._opener2closer[tok_type])
                # log.debug("content parentheticals: {}".format(parentheticals))
                # log.debug("Parsed {!r} (nested={}); next token={!r}".format(parenthetical, nested, self.next_tok))
                # if not parts and not nested and not self._peek("WS"):
                if not nested and not self._peek("WS") and self.next_tok is not None and len(parentheticals) == 1:
                    text += self._nested_fmts[tok_type].format(parentheticals[0])
                elif len(parentheticals) == 1 and isinstance(parentheticals[0], str):
                    parts.append((parentheticals[0], nested, tok_type))
                else:
                    parts.extend(parentheticals)
                    # parts.append((parenthetical, nested, tok_type))
            elif self._accept_any(self._content_tokens):
                text += self.tok.value
            elif self._accept("TIME"):
                if self.prev_tok.type == "DASH" or not self.next_tok:
                    if time_part:
                        fmt = "Unexpected {!r} token {!r} in {!r} (time {!r} was already found)"
                        raise UnexpectedTokenError(fmt.format(
                            self.next_tok.type, self.next_tok.value, self._full, time_part
                        ))
                    time_part = self.tok.value.strip()
                    # parts.append(self.tok.value.strip())
                else:
                    text += self.tok.value
            else:
                raise UnexpectedTokenError("Unexpected {!r} token {!r} in {!r}".format(
                    self.next_tok.type, self.next_tok.value, self._full
                ))

        if text:
            parts.append(text)

        if self._selective_recombine:
            single_idxs = set()
            had_nested = False
            for i, part in enumerate(parts):
                if isinstance(part, tuple):
                    nested = part[1]
                    had_nested = had_nested or nested
                    if not nested:
                        single_idxs.add(i)

            # log.debug("{!r} => {} [nested: {}][singles: {}]".format(self._full, parts, had_nested, sorted(single_idxs)))
            if had_nested and single_idxs:
                single_idxs = sorted(single_idxs)
                while single_idxs:
                    i = single_idxs.pop(0)
                    for ti in (i - 1, i + 1):
                        if (ti < 0) or (ti > (len(parts) - 1)):
                            continue
                        if isinstance(parts[ti], str) and parts[ti].strip():
                            parenthetical, nested, tok_type = parts[i]
                            formatted = self._nested_fmts[tok_type].format(parenthetical)
                            parts[ti] = (formatted + parts[ti]) if ti > i else (parts[ti] + formatted)
                            parts.pop(i)
                            single_idxs = [idx - 1 for idx in single_idxs]
                            break

        cleaned = (part for part in map(str.strip, (p[0] if isinstance(p, tuple) else p for p in parts)) if part)
        return [part for part in cleaned if part not in "\"“()（）[]"], time_part


def synonym_pattern(name):
    parts = name.lower().split()
    for synonym_set in SYNONYMS:
        for i, part in enumerate(list(parts)):
            if part in synonym_set:
                parts[i] = "(?:{})".format("|".join(synonym_set.values()))

    pattern = r"\s+".join(parts)
    # log.debug("Synonym pattern: {!r} => {!r}".format(name, pattern))
    return re.compile(pattern, re.IGNORECASE)


def sanitize(text):
    return text.translate(PATH_SANITIZATION_TABLE)


def unsurround(a_str, *chars):
    chars = chars or (("\"", "\""), ("(", ")"), ("“", "“"))
    for a, b in chars:
        if a_str.startswith(a) and a_str.endswith(b):
            a_str = a_str[1:-1].strip()
    return a_str


def _normalize_title(title):
    try:
        space_rx = _normalize_title._space_rx
    except AttributeError:
        space_rx = _normalize_title._space_rx = re.compile(r"\s+")
    return space_rx.sub(" ", fuzz_utils.full_process(title, force_ascii=False))


def parse_intro_name(text):
    first_sentence = text.strip().partition(". ")[0].strip()  # Note: space is intentional
    parser = ParentheticalParser()
    try:
        parts = parser.parse(first_sentence)    # Note: returned strs already stripped of leading/trailing spaces
    except Exception as e:
        raise ValueError("Unable to parse artist name from intro: {}".format(first_sentence)) from e

    # log.debug("{!r} => {}".format(first_sentence, parts))
    if len(parts) == 1:
        base, details = parts[0], ""
    else:
        base, details = parts[:2]
    if " is " in base:
        base = base[:base.index(" is ")].strip()
        eng, cjk = eng_cjk_sort(base)
        return eng, cjk, None, None, None
    elif is_any_cjk(details):
        return base, details, None, None, None
    elif not contains_any_cjk(details):
        eng, cjk = eng_cjk_sort(base)
        return eng, cjk, None, None, None
    elif details.lower().endswith("ost") and base.lower().endswith("ost") and contains_any_cjk(details):
        eng, cjk = eng_cjk_sort((base, details), permissive=True)
        return eng, cjk, None, None, None
    elif base.endswith(")") and details.endswith(")"):
        base_parts = parser.parse(base)
        details_parts = parser.parse(details)
        if len(base_parts) == len(details_parts) ==  2 and base_parts[1] == details_parts[1]:
            eng, cjk = eng_cjk_sort((base_parts[0], details_parts[0]), permissive=True)
            return eng, cjk, None, None, [base_parts[1]]

    cjk = ""
    found_hangul = False
    stylized = None
    aka = None
    aka_leads = ("aka", "a.k.a.", "also known as", "or simply")
    info = []
    for part in map(str.strip, re.split("[;,]", details)):
        lc_part = part.lower()
        if lc_part.startswith("stylized as"):
            stylized = part[11:].strip()
        elif is_any_cjk(part) and not found_hangul:
            found_hangul = is_hangul(part)
            cjk = part
        elif ":" in part and not found_hangul:
            _lang_name, cjk = eng_cjk_sort(tuple(map(str.strip, part.split(":", 1))))
            found_hangul = is_hangul(cjk)
        elif lc_part.endswith((" ver.", " ver")):
            info.append(part)
        elif not aka:
            for lead in aka_leads:
                if lc_part.startswith(lead):
                    aka = part[len(lead):].strip()
                    break

    return base, cjk, stylized, aka, info


def split_name(name, unused=False, check_keywords=True):
    """
    :param str name: A song/album/artist title
    :param bool unused: Return a 3-tuple instead of a 2-tuple, with the 3rd element being the content that was discarded
    :param bool check_keywords: Check for some key words at the start of the English name, such as 'inst.' or 'feat.'
      and count that as an invalid English name part
    :return tuple: (english, cjk)
    """
    name = name.strip()
    parser = ParentheticalParser()
    try:
        parts = parser.parse(name)   # Note: returned strs already stripped of leading/trailing spaces
    except Exception as e:
        raise ValueError("Unable to split {!r} into separate English/CJK strings".format(name)) from e

    if not parts:
        raise ValueError("Unable to split {!r} into separate English/CJK strings (nothing was parsed)".format(name))

    eng, cjk, not_used = None, None, None
    langs = categorize_langs(parts)
    s = "s" if len(parts) > 1 else ""
    log.log(9, "ParentheticalParser().parse({!r}) => {} part{}: {} ({})".format(name, len(parts), s, parts, langs))
    if len(parts) == 1:
        try:
            eng, cjk = eng_cjk_sort(parts[0], langs[0])
        except ValueError as e:
            raise ValueError("Unable to split {!r} into separate English/CJK strings".format(name)) from e
    elif len(parts) == 2:
        if LangCat.MIX not in langs and len(set(langs)) == 2:
            eng, cjk = eng_cjk_sort(parts, langs)           # Name (other lang)
        elif langs[0] == LangCat.MIX and langs[1] != LangCat.MIX and has_parens(parts[0]):
            eng, cjk = split_name(parts[0])                 # Soloist (other lang) (Group single lang)
            not_used = parts[1]
        elif langs[0] != LangCat.MIX and langs[1] == LangCat.MIX and has_parens(parts[1]):
            eng, cjk = eng_cjk_sort(parts[0], langs[0])     # Soloist single lang (Group (group other lang))
            try:
                not_used = split_name(parts[1])
            except Exception:
                not_used = parts[1]
        elif langs == (LangCat.MIX, LangCat.MIX) and all(has_parens(p) for p in parts):
            eng, cjk = split_name(parts[0])                 # Soloist (other lang) [Group (group other lang)]
            try:
                not_used = split_name(parts[1])
            except Exception:
                not_used = parts[1]
    elif len(parts) == 3:
        if LangCat.MIX not in langs and len(set(langs)) == 2:
            if langs[0] == langs[1] != langs[2]:
                try:
                    soloist_b, group_b = parser.parse(parts[2])
                except ValueError:  # Not enough values to unpack => no parens, or they weren't followed by whitespace
                    eng, cjk = eng_cjk_sort(parts[0], langs[0])         # Soloist (group) (group other lang)
                    not_used = parts[1:]
                else:
                    soloist_a, group_a = parts[:2]          # Soloist (group) (soloist other lang (group other lang))
                    eng, cjk = eng_cjk_sort((soloist_a, soloist_b), langs[1:])
                    not_used = eng_cjk_sort((group_a, group_b), langs[1:])
            else:
                eng, cjk = eng_cjk_sort(parts[:2], langs[:2])           # Name (other lang) (Group|extra single lang)
                not_used = parts[2]

    if not eng and not cjk:
        # traceback.print_stack()
        raise ValueError("Unable to split {!r} into separate English/CJK strings".format(name))

    if check_keywords and eng.lower().startswith(("feat.", "featuring", "inst.", "instrumental")):
        log.debug("Shuffling return values due to keywords: {}".format((eng, cjk, not_used)))
        if not_used is None:
            not_used = eng
        elif isinstance(not_used, str):
            not_used = [not_used, eng]
        else:
            not_used = list(not_used)
            not_used.append(eng)
        eng = ""
        if not cjk:
            raise ValueError("Unable to split {!r} into separate English/CJK strings".format(name))

    return (eng, cjk, not_used) if unused else (eng, cjk)


def eng_cjk_sort(strs, langs=None, permissive=False):
    """
    :param str|tuple|list|iterator strs: A single string or a tuple/list with 2 elements
    :param LangCat|tuple|None langs: A single Langs value or a 2-tuple of Langs (ENG/CJK only) or None
    :param bool permissive: Allow a 2-tuple of english and mixed rather than requiring no english in the second str
    :return tuple: (str(eng), str(cjk))
    """
    # noinspection PyTypeChecker
    if isinstance(strs, (types.GeneratorType, map)):
        strs = list(strs)
    if langs is None:
        langs = categorize_langs([strs] if isinstance(strs, str) else strs)
        if isinstance(strs, str):
            langs = langs[0]
    if not isinstance(strs, str) and len(strs) == 1:
        langs = langs[0]
        strs = strs[0]
    if langs == (LangCat.ENG, LangCat.CJK) or (permissive and langs == (LangCat.ENG, LangCat.MIX)):
        return strs
    elif langs == (LangCat.CJK, LangCat.ENG) or (permissive and langs == (LangCat.MIX, LangCat.ENG)):
        return reversed(strs)
    elif isinstance(strs, str):
        if langs == LangCat.ENG:
            return strs, ""
        elif langs == LangCat.CJK:
            return "", strs
    raise ValueError("Unexpected values: strs={!r}, langs={!r}".format(strs, langs))


def has_parens(text):
    return any(c in text for c in "()[]")


class LangCat(Enum):
    ENG = 1
    CJK = 2
    MIX = 3


def categorize_lang(s):
    return LangCat.CJK if is_any_cjk(s) else LangCat.MIX if contains_any_cjk(s) else LangCat.ENG


def categorize_langs(strs):
    return tuple(categorize_lang(s) for s in strs)


def parse_discography_entry(artist, ele, album_type, lang, type_idx):
    ele_text = ele.text.strip()
    try:
        parsed = ParentheticalParser().parse(ele_text)
    except Exception as e:
        log.warning("Unhandled discography entry format {!r} for {}".format(ele_text, artist), extra={"red": True})
        return None
    # else:
    #     log.debug("Parsed {!r} => {}".format(ele_text, parsed))

    # links = [
    #     (t, h[6:] if h.startswith("/wiki/") else h)
    #     for t, h in ((a.text, a.get("href") or "") for a in ele.find_all("a"))
    # ]
    links = link_tuples(ele.find_all("a"))
    linkd = dict(links)
    try:
        num_type_rx = parse_discography_entry._num_type_rx
    except AttributeError:
        num_type_rx = parse_discography_entry._num_type_rx = re.compile(r"_\d$")
    base_type = album_type and (album_type[:-2] if num_type_rx.search(album_type) else album_type).lower() or ""
    is_feature = base_type in ("features", "collaborations_and_features")
    if is_feature and parsed[0].endswith("-"):
        primary_artist = parsed.pop(0)[:-1].strip()
        primary_uri = links[0][1] if links and links[0][0] == primary_artist else None
        log.debug("Primary artist={}, links[0]={}".format(primary_artist, links[0] if links else None))
    else:
        primary_artist = artist.english_name
        primary_uri = artist._uri_path
    year = int(parsed.pop()) if len(parsed[-1]) == 4 and parsed[-1].isdigit() else None
    title = parsed.pop(0)
    collabs, misc_info = [], []
    for item in parsed:
        lc_item = item.lower()
        if lc_item.startswith(("with ", "feat. ", "feat ", "as ")) or "feat." in lc_item:
            # item = item.split(maxsplit=1)[1]    # remove the with/feat prefix
            for collab in str2list(item, pat="^(?:with|feat\.?|as) | and |,|;|&| feat\.? | featuring | with "):
                try:
                    soloist, of_group = collab.split(" of ")
                except Exception as e:
                    collabs.append({"artist": split_name(collab), "artist_href": linkd.get(collab)})
                else:
                    collabs.append({
                        "artist": split_name(soloist), "artist_href": linkd.get(soloist),
                        "of_group": split_name(of_group), "group_href": linkd.get(of_group),
                    })
            # item_collabs = set(str2list(item))
            # if links:
            #     collabs.update({text: href for text, href in links if text in item_collabs})
            # else:
            #     collabs.update({name: None for name in item_collabs})
        else:
            misc_info.append(item)

    collab_names, collab_hrefs = set(), set()
    for collab in collabs:
        # log.debug("Collaborator for {}: {}".format(title, collab))
        collab_names.add(collab["artist"][0])
        collab_hrefs.add(collab["artist_href"])
        of_group = collab.get("of_group")
        if of_group:
            collab_names.add(of_group[0])
            collab_hrefs.add(collab.get("group_href"))

    if artist.english_name not in collab_names or artist._uri_path not in collab_hrefs:
        if primary_artist != artist.english_name:
            collabs.append({"artist": (artist.english_name, artist.cjk_name), "artist_href": artist._uri_path})
            collab_names.add(artist.english_name)
            collab_hrefs.add(artist._uri_path)

    # if artist.english_name not in collabs or artist._uri_path not in collabs.values():
    #     if primary_artist != artist.english_name:
    #         collabs[artist.english_name] = artist._uri_path

    is_feature_or_collab = base_type in ("features", "collaborations", "collaborations_and_features")
    is_ost = base_type in ("ost", "osts")

    # non_artist_links = [lnk for lnk in links if lnk[1] and lnk[1] != primary_uri and lnk[1] not in collabs.values()]
    non_artist_links = [lnk for lnk in links if lnk[1] and lnk[1] != primary_uri and lnk[1] not in collab_hrefs]
    if non_artist_links:
        if len(non_artist_links) > 1:
            fmt = "Too many non-artist links found: {}\nFrom li: {}\nParsed parts: {}\nbase_type={}"
            raise WikiEntityParseException(fmt.format(non_artist_links, ele, parsed, base_type))

        link_text, link_href = non_artist_links[0]
        if title != link_text and not is_feature_or_collab:
            # if is_feature_or_collab: likely a feature / single with a link to a collaborator
            if not any(title.replace("(", c).replace(")", c) == link_text for c in "-~"):
                log.debug("Unexpected first link text {!r} for album {!r}".format(link_text, title))

        if link_href.startswith(("http://", "https://")):
            url = urlparse(link_href)
            if url.hostname == "en.wikipedia.org":
                uri_path = url.path[6:]
                wiki = "en.wikipedia.org"
                # Probably a collaboration song, so title is likely a song and not the album title
            else:
                log.debug("Found link from {}'s discography to unexpected site: {}".format(artist, link_href))
                uri_path = None
                wiki = "kpop.fandom.com"
        else:
            uri_path = link_href or None
            wiki = "kpop.fandom.com"
    else:
        if is_ost:
            try:
                ost_rx = parse_discography_entry._ost_rx
            except AttributeError:
                ost_rx = parse_discography_entry._ost_rx = re.compile("(.*? OST).*")
            m = ost_rx.match(title)
            if m:
                non_part_title = m.group(1).strip()
                uri_path = non_part_title.replace(" ", "_")
            else:
                uri_path = title.replace(" ", "_")
            wiki = "wiki.d-addicts.com"
        elif is_feature_or_collab:
            uri_path = None
            wiki = "kpop.fandom.com"
            # Probably a collaboration song, so title is likely a song and not the album title
        else:
            uri_path = None
            wiki = "kpop.fandom.com"
            # May be an album without a link, or a repackage detailed on the same page as the original

    info = {
        "title": title, "primary_artist": (primary_artist, primary_uri), "type": album_type, "base_type": base_type,
        "year": year, "collaborators": collabs, "misc_info": misc_info, "language": lang, "uri_path": uri_path,
        "wiki": wiki, "is_feature_or_collab": is_feature_or_collab, "is_ost": is_ost,
        "num": "{}{}".format(type_idx, num_suffix(type_idx))
    }
    return info


def str2list(text, pat="^(?:with|feat\.?|as) | and |,|;|&| feat\.? | featuring | with "):
    """Convert a string list to a proper list"""
    try:
        compiled_pats = str2list._compiled_pats
    except AttributeError:
        compiled_pats = str2list._compiled_pats = {}
    try:
        pat_rx = compiled_pats[pat]
    except KeyError:
        pat_rx = compiled_pats[pat] = re.compile(pat)
    return [val for val in map(str.strip, pat_rx.split(text)) if val]


def link_tuples(anchors):
    tuple_gen = ((a.text, a.get("href") or "") for a in anchors)
    return [(text, href[6:] if href.startswith("/wiki/") else href) for text, href in tuple_gen if href]


def parse_aside(aside):
    """
    Parse the 'aside' element from a wiki page into a more easily used data format

    :param aside: Beautiful soup 'aside' element
    :return dict: The parsed data
    """
    try:
        comma_fix_rx = parse_aside._comma_fix_rx
        date_comment_rx = parse_aside._date_comment_rx
        len_rx = parse_aside._len_rx
        len_comment_rx = parse_aside._len_comment_rx
    except AttributeError:
        comma_fix_rx = parse_aside._comma_fix_rx = re.compile(r"\s+,")
        date_comment_rx = parse_aside._date_comment_rx = re.compile(r"^(\S+ \d+\s*, \d{4})\s*\((.*)\)$")
        len_rx = parse_aside._len_rx = re.compile(r"^\d*:?\d+:\d{2}$")
        len_comment_rx = parse_aside._len_comment_rx = re.compile(r"^(\d*:?\d+:\d{2})\s*\((.*)\)$")

    unexpected_date_fmt = "Unexpected release date format in: {}"
    parsed = {}
    for ele in aside.children:
        tag_type = ele.name
        if isinstance(ele, NavigableString) or tag_type in ("figure", "section"):    # newline/image/footer
            continue

        key = ele.get("data-source")
        if not key or key == "image":
            continue
        elif tag_type == "h2":
            value = ele.text
        else:
            val_ele = list(ele.children)[-1]
            if isinstance(val_ele, NavigableString):
                val_ele = val_ele.previous_sibling

            if key == "released":
                value = []
                for s in val_ele.stripped_strings:
                    cleaned_date = comma_fix_rx.sub(",", s)
                    try:
                        dt = datetime_with_tz(cleaned_date, "%B %d, %Y")
                    except Exception as e:
                        if value and not value[-1][1]:
                            value[-1] = (value[-1][0], unsurround(s))
                        else:
                            m = date_comment_rx.match(s)
                            if m:
                                cleaned_date = comma_fix_rx.sub(",", m.group(1))
                                try:
                                    dt = datetime_with_tz(cleaned_date, "%B %d, %Y")
                                except Exception as e1:
                                    raise ValueError(unexpected_date_fmt.format(val_ele)) from e1
                                else:
                                    value.append((dt, m.group(2)))
                            else:
                                raise ValueError(unexpected_date_fmt.format(val_ele)) from e
                    else:
                        value.append((dt, None))
            elif key == "length":
                value = []
                for s in val_ele.stripped_strings:
                    if len_rx.match(s):
                        value.append((s, None))
                    else:
                        m = len_comment_rx.match(s)
                        if m:
                            value.append(tuple(m.groups()))
                        elif value and value[-1] and not value[-1][1]:
                            value[-1] = (value[-1][0], unsurround(s))
                        else:
                            raise ValueError("Unexpected length format in: {}".format(val_ele))
            elif key in ("agency", "artist", "associated", "composer", "current", "label", "writer"):
                anchors = list(val_ele.find_all("a"))
                if anchors:
                    value = dict(link_tuples(anchors))
                    # value = {a.text: a.get("href") for a in anchors}
                else:
                    ele_children = list(val_ele.children)
                    if not isinstance(ele_children[0], NavigableString) and ele_children[0].name == "ul":
                        value = {li.text: None for li in ele_children[0].find_all("li")}
                    else:
                        value = {name: None for name in str2list(val_ele.text)}
            elif key in ("format", ):
                ele_children = list(val_ele.children)
                if not isinstance(ele_children[0], NavigableString) and ele_children[0].name == "ul":
                    value = [li.text for li in ele_children[0].find_all("li")]
                else:
                    value = str2list(val_ele.text)
            else:
                value = val_ele.text
        parsed[key] = value
    return parsed


def _album_num_type(details):
    alb_broad_type = next((val for val in ("album", "single") if val in details), None)
    if alb_broad_type:
        alb_type_desc = details[:details.index(alb_broad_type) + 1]
        if "full-length" in alb_type_desc:
            alb_type_desc.remove("full-length")
        num = NUMS.get(alb_type_desc[0])
        return num, " ".join(alb_type_desc[1:] if num else alb_type_desc)
    elif len(details) > 1 and details[0] == "song" and details[1] == "by":
        return None, "single"
    raise ValueError("Unable to determine album type from details: {}".format(details))


def _first_side_info_val(side_info, key):
    try:
        return side_info.get(key, [])[0][0]
    except IndexError:
        return None


def parse_album_page(uri_path, clean_soup, side_info):
    """
    :param clean_soup: The :attr:`WikiEntity._clean_soup` value for an album
    :param dict side_info: Parsed 'aside' element contents
    :return list: List of dicts representing the albums found on the given page
    """
    bad_intro_fmt = "Unexpected album intro sentence format in {}: {!r}"
    album0 = {}
    album1 = {}
    intro_text = clean_soup.text.strip()
    try:
        intro_rx = parse_album_page._intro_rx
    except AttributeError:
        intro_rx = parse_album_page._intro_rx = re.compile(r"^(.*?)\s+is\s+(?:a|the)\s+(.*?)\.\s")
    intro_match = intro_rx.match(intro_text)
    if not intro_match:
        raise WikiEntityParseException(bad_intro_fmt.format(uri_path, intro_text[:200]))

    album0["title_parts"] = parse_intro_name(intro_match.group(1))  # base, cjk, stylized, aka, info
    details_str = intro_match.group(2)
    details_str = details_str.replace("full length", "full-length").replace("mini-album", "mini album")
    details = list(details_str.split())
    if (details[0] == "repackage") or (details[0] == "new" and details[1] == "edition"):
        album0["repackage"] = True
        for i, ele in enumerate(details):
            if ele.endswith(("'s", "S'", "s'")):
                artist_idx = i
                break
        else:
            raise WikiEntityParseException(bad_intro_fmt.format(uri_path, intro_text[:200]))

        try:
            album0["num"], album0["type"] = _album_num_type(details[artist_idx:])
        except ValueError as e:
            raise WikiEntityParseException(bad_intro_fmt.format(uri_path, intro_text[:200])) from e

        for a in clean_soup.find_all("a"):
            if details_str.endswith(a.text):
                href = a.get("href")
                if href:
                    album0["repackage_of_href"] = href[6:]
                    album0["repackage_of_title"] = a.text
                break
        else:
            fmt = "Unable to find link to repackaged version of {}; details={}"
            raise WikiEntityParseException(fmt.format(uri_path, details))
    elif (details[0] == "original" and details[1] == "soundtrack") or (details[0].lower() in ("ost", "soundtrack")):
        album0["num"] = None
        album0["type"] = "OST"
        album0["repackage"] = False
    else:
        album0["repackage"] = False
        try:
            album0["num"], album0["type"] = _album_num_type(details)
        except ValueError as e:
            raise WikiEntityParseException(bad_intro_fmt.format(uri_path, intro_text[:200])) from e

        try:
            repkg_rx = parse_album_page._repkg_rx
        except AttributeError:
            repkg_rx = parse_album_page._repkg_rx = re.compile("A repackage titled (.*) (?:was|will be) released")
        repkg_match = repkg_rx.search(intro_text)
        if repkg_match:
            repkg_title = repkg_match.group(1)
            releases = side_info.get("released", [])
            repkg_dt = next((dt for dt, note in releases if note and note.lower() == "repackage"), None)
            if repkg_dt:
                album1["title_parts"] = parse_intro_name(repkg_title)   # base, cjk, stylized, aka, info
                album1["length"] = next((val for val, note in side_info.get("length", []) if note == "repackage"), None)
                album1["num"] = album0["num"]
                album1["type"] = album0["type"]
                album1["repackage"] = True
                album1["repackage_of_href"] = uri_path
                album1["repackage_of_title"] = repkg_title
                album0["repackage_href"] = uri_path
                album0["repackage_title"] = repkg_title
                album1["released"] = repkg_dt
                album1["links"] = []
            else:
                for a in clean_soup.find_all("a"):
                    if a.text == repkg_title:
                        href = a.get("href")
                        if href:
                            album0["repackage_href"] = href[6:]
                            album0["repackage_title"] = repkg_title
                        break
                else:
                    raise WikiEntityParseException("Unable to find link to repackaged version of {}".format(uri_path))

    links = []
    for ele in clean_soup.children:
        if isinstance(ele, NavigableString):
            continue
        elif ele.name in ("h1", "h2", "h3", "h4"):
            break
        links.extend(link_tuples(ele.find_all("a")))
        # links.extend((a.text, a.get("href")) for a in ele.find_all("a"))
    album0["links"] = links
    album0["released"] = _first_side_info_val(side_info, "released")
    album0["length"] = _first_side_info_val(side_info, "length")
    album0["name"] = side_info.get("name")

    albums = [album0, album1] if album1 else [album0]
    for album in albums:
        album["artists"] = side_info.get("artist", {})

    try:
        track_lists = parse_album_tracks(uri_path, clean_soup, links)
    except NoTrackListException as e:
        if not album1 and "single" in album0["type"].lower():
            eng, cjk = album0["title_parts"][:2]
            title_info = album0["title_parts"][-1]
            _name = "{} ({})".format(eng, cjk)
            if title_info:
                _name = " ".join(chain((_name,), map("({})".format, title_info)))
            album0["tracks"] = {
                "section": None, "tracks": [
                    # {"name_parts": (eng, cjk), "num": 1, "length": album0["length"] or "-1:00", "misc": title_info},
                    parse_track_info(1, _name, uri_path, album0["length"] or "-1:00")
                ]
            }
        else:
            raise e
    else:
        if album1:
            if len(track_lists) != 2:
                err_msg = "Unexpected track section count for original+repackage combined page {}".format(uri_path)
                raise WikiEntityParseException(err_msg)
            for i, album in enumerate(albums):
                album["tracks"] = track_lists[i]
        else:
            if len(track_lists) == 1:
                album0["tracks"] = track_lists[0]
            else:
                album0["track_lists"] = track_lists

    return albums


def parse_album_tracks(uri_path, clean_soup, intro_links):
    """
    Parse the Track List section of a Kpop Wiki album/single page.

    :param str uri_path: The uri_path of the page to include in log messages
    :param clean_soup: The cleaned up bs4 soup for the page content
    :param list intro_links: List of tuples of (text, href) containing links from the intro
    :return list: List of dicts of album parts/editions/disks, with a track list per section
    """
    track_list_span = clean_soup.find("span", id="Track_list") or clean_soup.find("span", id="Tracklist")
    if not track_list_span:
        raise NoTrackListException("Unable to find track list for album {}".format(uri_path))

    h2 = track_list_span.find_parent("h2")
    if not h2:
        raise WikiEntityParseException("Unable to find track list header for album {}".format(uri_path))

    disk_rx = re.compile(r"^Dis[ck]\s+(\S+)\s*[{}]?\s*(.*)$".format(DASH_CHARS + ":"), re.IGNORECASE)
    unexpected_num_fmt = "Unexpected disk number format for {}: {!r}"
    parser = ParentheticalParser(False)
    track_lists = []
    section, links, disk = None, [], 1
    for ele in h2.next_siblings:
        if isinstance(ele, NavigableString):
            continue

        ele_name = ele.name
        if ele_name == "h2":
            break
        elif ele_name in ("ol", "ul"):
            if section and (section if isinstance(section, str) else section[0]).lower().startswith("dvd"):
                section, links = None, []
                continue

            tracks = []
            for i, li in enumerate(ele.find_all("li")):
                track_links = link_tuples(li.find_all("a"))
                all_links = list(set(track_links + intro_links))
                track = parse_track_info(i + 1, li.text, uri_path, include={"links": track_links}, links=all_links)
                tracks.append(track)

            track_lists.append({"section": section, "tracks": tracks, "links": links, "disk": disk})
            section, links = None, []
        else:
            for junk in ele.find_all(class_="editsection"):
                junk.extract()
            section = ele.text
            links = link_tuples(ele.find_all("a"))
            # links = [(a.text, a.get("href")) for a in ele.find_all("a")]
            if has_parens(section):
                try:
                    section = parser.parse(section)
                except Exception as e:
                    pass

            disk_section = section if not section or isinstance(section, str) else section[0]
            if disk_section and disk_section.lower().startswith(("disk", "disc")):
                m = disk_rx.match(disk_section)
                if not m:
                    raise WikiEntityParseException(unexpected_num_fmt.format(uri_path, disk_section))

                disk_raw = m.group(1).strip().lower()
                try:
                    disk = NUM2INT[disk_raw]
                except KeyError as e:
                    try:
                        disk = int(disk_raw)
                    except (TypeError, ValueError) as e1:
                        raise WikiEntityParseException(unexpected_num_fmt.format(uri_path, m.group(1))) from e1
                disk_section = m.group(2).strip() or None
                if isinstance(section, str):
                    section = disk_section
                else:
                    section[0] = disk_section
            else:
                disk = 1

    return track_lists


def _combine_name_parts(name_parts):
    langs = categorize_langs(name_parts)
    last = None
    for i, lang in enumerate(langs):
        if lang == last:
            prefix = name_parts[:i-1]
            suffix = name_parts[i+1:]
            combined = "{} ({})".format(*name_parts[i-1:i+1])
            return prefix + [combined] + suffix
        last = lang
    combined = "{} ({})".format(*name_parts[:2])
    return [combined] + name_parts[2:]


def parse_track_info(idx, text, source, length=None, *, include=None, links=None):
    """
    Split and categorize the given text to identify track metadata such as length, collaborators, and english/cjk name
    parts.

    :param int|str idx: Track number / index in list (1-based)
    :param str|container text: The text to be parsed, or already parsed/split text
    :param str source: uri_path or other identifier for the source of the text being parsed (to add context to errors)
    :param str|None length: Length of the track, if known (MM:SS format)
    :param dict|None include: Additional fields to be included in the returned track dict
    :param list|None links: List of tuples of (text, href) that were in the html for the given text
    :return dict: The parsed track information
    """
    if isinstance(idx, str):
        idx = idx.strip()
        if idx.endswith("."):
            idx = idx[:-1]
        try:
            idx = int(idx)
        except ValueError as e:
            fmt = "Error parsing track number {!r} for {!r} from {}: {}"
            raise TrackInfoParseException(fmt.format(idx, text, source, e)) from e

    track = {"num": idx, "length": "-1:00"}
    if include:
        track.update(include)
    if isinstance(text, str):
        text = unsurround(text.strip(), *(c*2 for c in QMARKS))
        try:
            parsed, time_part = TrackInfoParser().parse(text)
        except Exception as e:
            raise TrackInfoParseException("Error parsing track from {}: {!r}".format(source, text)) from e
    else:
        parsed = text
        time_part = None

    # log.debug("{!r} => {}".format(text, parsed))
    if length:
        track["length"] = length
    if time_part:
        if length:
            fmt = "Length={!r} was provided for track {}/{!r} from {}, but it was also parsed to be {!r}"
            raise TrackInfoParseException(fmt.format(length, idx, text, source, time_part))
        track["length"] = time_part

    try:
        lang_map = parse_track_info._lang_map
        version_types = parse_track_info._version_types
        misc_indicators = parse_track_info._misc_indicators
    except AttributeError:
        lang_map = parse_track_info._lang_map = {
            "chinese": "Chinese", "chn": "Chinese",
            "english": "English", "en": "English", "eng": "English",
            "japanese": "Japanese", "jp": "Japanese", "jap": "Japanese",
            "korean": "Korean", "kr": "Korean", "kor": "Korean", "ko": "Korean",
            "spanish": "Spanish"
        }
        version_types = parse_track_info._version_types = (
            "inst", "acoustic", "ballad", "original", "remix", "r&b", "band", "karaoke", "special", "full length",
            "single", "album", "radio", "limited", "normal", "english rap", "rap", "piano", "acapella", "edm", "stage",
            "live"
        )
        misc_indicators = parse_track_info._misc_indicators = ( # spaces intentional
            "bonus", " ost", " mix", "remix", "special track", "prod. by", "produced by", "director's", " only",
            "remaster", "intro"
        )

    name_parts, name_langs, collabs, misc, unknown = [], [], [], [], []
    link_texts = set(link[0] for link in links) if links else None
    for n, part in enumerate(parsed):
        if n == 0:
            # log.debug("{!r}: Adding to name parts: {!r}".format(text, part))
            name_parts.append(part)
            name_langs.append(categorize_lang(part))
            continue
        elif not part:
            continue

        lc_part = part.lower()
        feat = next((val for val in FEAT_ARTIST_INDICATORS if val in lc_part), None)
        duet_etc = next((val for val in (" duet", " trio") if val in lc_part), None)
        if feat:
            collab_part = part[len(feat):].strip() if lc_part.startswith(feat) else part
            collabs.extend(str2list(collab_part, pat="(?: and |,|;|&| feat\.? | featuring | with )"))
            # collabs.extend(str2list(part[len(feat):].strip()))
        elif duet_etc:
            collab_part = part[:-len(duet_etc)].strip()
            collabs.extend(str2list(collab_part, pat="(?: and |,|;|&| feat\.? | featuring | with )"))
        elif lc_part.endswith(" solo"):
            track["artist"] = part[:-5].strip()
        elif lc_part.endswith((" ver.", " ver", " version", " edition", " ed.")):
            value = part.rsplit(maxsplit=1)[0]
            if lc_part.startswith(version_types):
                track["version"] = value
            else:
                try:
                    track["language"] = lang_map[value.lower()]
                except KeyError:
                    log.debug("Found unexpected version text in {!r}: {!r}".format(text, value), extra={"color": 100})
                    track["version"] = value
        elif lc_part.startswith(("inst", "acoustic")):
            track["version"] = part
        elif any(val in lc_part for val in misc_indicators):
            misc.append(part)
        elif links and any(link_text in part for link_text in link_texts):
            split_part = str2list(part, pat="(?: and |,|;|&| feat\.? | featuring | with )")
            if any(sp in link_texts for sp in split_part):
                collabs.extend(split_part)                  # assume links are to artists
            elif len(set(name_langs)) < 2:
                # log.debug("{!r}: Adding to name parts: {!r}".format(text, part))
                name_parts.append(part)
                name_langs.append(categorize_lang(part))
            else:
                log.debug("Assuming {!r} from {!r} > {!r} is misc [no link matches]".format(part, source, text), extra={"color": 70})
                misc.append(part)
        else:
            if len(set(name_langs)) < 2:
                # log.debug("{!r}: Adding to name parts: {!r}".format(text, part))
                name_parts.append(part)
                name_langs.append(categorize_lang(part))
            else:
                log.debug("Assuming {!r} from {!r} > {!r} is misc".format(part, source, text), extra={"color": 70})
                misc.append(part)

    if len(name_parts) > 2:
        log.log(9, "High name part count in {} [{!r} =>]: {}".format(source, text, name_parts))
        while len(name_parts) > 2:
            name_parts = _combine_name_parts(name_parts)

    try:
        track["name_parts"] = eng_cjk_sort(name_parts[0] if len(name_parts) == 1 else name_parts, tuple(name_langs))
    except ValueError:
        track["name_parts"] = tuple(name_parts) if len(name_parts) == 2 else (name_parts[0], "")

    if collabs:
        track["collaborators"] = sorted(collabs)
    if misc:
        track["misc"] = misc
    if unknown:
        track["unknown"] = unknown

    return track


def parse_drama_wiki_info_list(uri_path, info_ul):
    info = {}
    for i, li in enumerate(info_ul.find_all("li")):
        try:
            key, value = map(str.strip, li.text.strip().split(":", 1))
        except ValueError as e:
            fmt = "Error splitting key:value pair {!r} from {}: {}"
            raise WikiEntityParseException(fmt.format(li.text.strip(), uri_path, e)) from e
        key = key.lower()
        if i == 0 and key != "title":
            return None
        elif key == "title":
            try:
                value = eng_cjk_sort(map(str.strip, value.split("/")), permissive=True)
            except Exception as e:
                pass
        elif key == "release date":
            try:
                value = datetime_with_tz(value, "%Y-%b-%d")
            except Exception as e:
                log.debug("Error parsing release date {!r} for {}: {}".format(value, uri_path, e))
                pass
        elif key == "language":
            value = str2list(value)
        elif key == "artist":
            artists = str2list(value, pat="(?: and |,|;|&| feat\.? )")
            value = []
            for artist in artists:
                try:
                    soloist, of_group = artist.split(" of ")
                except Exception as e:
                    value.append({"artist": split_name(artist)})
                else:
                    value.append({"artist": split_name(soloist), "of_group": split_name(of_group)})
        elif key == "also known as":
            value = str2list(value)
        elif key == "original soundtrack":
            links = dict(link_tuples(li.find_all("a")))
            value = {value: links.get(value)}

        info[key] = value
    return info


def parse_ost_page(uri_path, clean_soup):
    first_h2 = clean_soup.find("h2")
    if not first_h2:
        raise WikiEntityParseException("Unable to find first OST part section in {}".format(uri_path))

    track_lists = []
    h2 = first_h2
    while True:
        # log.debug("Processing section: {}".format(h2))
        if not h2 or h2.next_element.get("id", "").lower() == "see_also":
            break

        section = h2.text
        info_ul = h2.find_next_sibling("ul")
        if not info_ul:
            break
        info = parse_drama_wiki_info_list(uri_path, info_ul)
        if info is None:
            return track_lists

        tracks = []
        track_table = info_ul.find_next_sibling("table")
        for tr in track_table.find_all("tr"):
            tds = tr.find_all("td")
            if tds:
                name_parts = list(tds[1].stripped_strings)
                if len(name_parts) == 1 and categorize_langs(name_parts)[0] == LangCat.MIX:
                    name_parts = split_name(name_parts[0], unused=True)
                elif all(part.lower().endswith("(inst.)") for part in name_parts):
                    name_parts = [part[:-7].strip() for part in name_parts]
                    name_parts.append("Inst.")

                track = parse_track_info(tds[0].text, name_parts, uri_path, include={"from_ost": True})
                track["collaborators"] = str2list(tds[2].text.strip())
                tracks.append(track)

        track_lists.append({"section": section, "tracks": tracks, "info": info})
        h2 = h2.find_next_sibling("h2")

    return track_lists


def parse_infobox(infobox):
    """
    Parse the 'infobox' element from a wiki page into a more easily used data format

    :param infobox: Beautiful soup <table class="infobox"> element
    :return dict: The parsed data
    """
    parsed = {}
    for i, tr in enumerate(infobox.find_all("tr")):
        # log.debug("Processing tr: {}".format(tr))
        if i == 0:
            parsed["name"] = tr.text.strip()
        elif i == 1:
            continue    # Image
        elif i == 2 and tr.find("th").get("colspan"):
            try:
                parsed["type"], artist = map(str.strip, tr.text.strip().split(" by "))
            except Exception as e:
                log.debug("Error processing infobox row {!r}: {}".format(tr, e))
                raise e

            for a in tr.find_all("a"):
                if a.text == artist:
                    href = a.get("href") or ""
                    parsed["artist"] = {artist: href[6:] if href.startswith("/wiki/") else href}
                    break
            else:
                parsed["artist"] = {artist: None}
        else:
            th = tr.find("th")
            if not th or th.get("colspan"):
                break
            key = th.text.strip().lower()
            val_ele = tr.find("td")

            if key == "released":
                value = []
                val = val_ele.text.strip()
                try:
                    dt = datetime_with_tz(val, "%d %B %Y")
                except Exception as e:
                    raise WikiEntityParseException("Unexpected release date format: {!r}".format(val)) from e
                else:
                    value.append((dt, None))
            elif key == "length":
                value = [(val_ele.text.strip(), None)]
            elif key == "also known as":
                value = [val for val in val_ele.stripped_strings if val]
            elif key in ("agency", "associated", "composer", "current", "label", "writer"):
                anchors = list(val_ele.find_all("a"))
                if anchors:
                    value = dict(link_tuples(anchors))
                    # value = {a.text: a.get("href") for a in anchors}
                else:
                    ele_children = list(val_ele.children)
                    if not isinstance(ele_children[0], NavigableString) and ele_children[0].name == "ul":
                        value = {li.text: None for li in ele_children[0].find_all("li")}
                    else:
                        value = {name: None for name in str2list(val_ele.text)}
            else:
                value = val_ele.text.strip()

            parsed[key] = value
    return parsed


def parse_wikipedia_album_page(uri_path, clean_soup, side_info):
    unexpected_num_fmt = "Unexpected disk number format for {}: {!r}"
    bad_intro_fmt = "Unexpected album intro sentence format in {}: {!r}"
    album0 = {}
    intro_text = clean_soup.text.strip()
    intro_match = re.match("^(.*?)\s+is\s+(?:a|the)\s+(.*?)\.\s", intro_text)
    if not intro_match:
        raise WikiEntityParseException(bad_intro_fmt.format(uri_path, intro_text[:200]))

    album0["title_parts"] = parse_intro_name(intro_match.group(1))  # base, cjk, stylized, aka, info

    details_str = intro_match.group(2)
    details = list(details_str.split())
    album0["repackage"] = False
    try:
        album0["num"], album0["type"] = _album_num_type(details)
    except ValueError as e:
        raise WikiEntityParseException(bad_intro_fmt.format(uri_path, intro_text[:200])) from e

    # links = []
    # for ele in clean_soup.children:
    #     if isinstance(ele, NavigableString):
    #         continue
    #     elif ele.name in ("h1", "h2", "h3", "h4"):
    #         break
    #     links.extend((a.text, a.get("href")) for a in ele.find_all("a"))
    # album0["links"] = links
    album0["released"] = _first_side_info_val(side_info, "released")
    album0["length"] = _first_side_info_val(side_info, "length")
    album0["name"] = side_info.get("name")
    album0["track_lists"] = []

    albums = [album0]
    disk_rx = re.compile(r"^Dis[ck]\s+(\S+)\s*[{}]?\s*(.*)$".format(DASH_CHARS + ":"), re.IGNORECASE)
    album = album0
    for track_tbl in clean_soup.find_all("table", class_="tracklist"):
        last_ele = track_tbl.previous_sibling
        while isinstance(last_ele, NavigableString):
            last_ele = last_ele.previous_sibling

        if last_ele and last_ele.name == "h3":
            title_parts = parse_intro_name(last_ele.text.strip())
            repkg_title = title_parts[0]
            album = {
                "track_lists": [], "title_parts": title_parts, "repackage": True, "repackage_of_href": uri_path,
                "repackage_of_title": repkg_title
            }
            if len(albums) == 1:
                album0["repackage_href"] = uri_path
                album0["repackage_title"] = repkg_title
            albums.append(album)

        section_th = track_tbl.find(lambda ele: ele.name == "th" and ele.get("colspan"))
        section = section_th.text.strip() if section_th else None
        if section and section.lower().startswith(("disk", "disc")):
            m = disk_rx.match(section)
            if not m:
                raise WikiEntityParseException(unexpected_num_fmt.format(uri_path, section))
            try:
                disk = NUM2INT[m.group(1).lower()]
            except KeyError as e:
                raise WikiEntityParseException(unexpected_num_fmt.format(uri_path, m.group(1))) from e
            section = m.group(2).strip() or None
        else:
            disk = 1

        tracks = []
        for tr in track_tbl.find_all("tr"):
            tds = tr.find_all("td")
            if len(tds) >= 3:
                tracks.append(parse_track_info(tds[0].text, tds[1].text, uri_path, tds[-1].text.strip()))

        album["track_lists"].append({"section": section, "tracks": tracks, "disk": disk})

    for album in albums:
        album["artists"] = side_info.get("artist", {})

    return albums


def edition_combinations(editions, next_track):
    next_track -= 1
    candidates = []
    for i in range(len(editions)):
        for combo in combinations(editions, i):
            tracks = sorted(t["num"] for t in chain.from_iterable(edition["tracks"] for edition in combo))
            if tracks and len(set(tracks)) == len(tracks) == max(tracks) == next_track and min(tracks) == 1:
                candidates.append(combo)

    if not candidates:
        for edition in editions:
            tracks = sorted(t["num"] for t in edition["tracks"])
            if tracks and len(set(tracks)) == len(tracks) == max(tracks) == next_track and min(tracks) == 1:
                candidates.append([edition])

    return list({tuple(e.get("section") or "" for e in combo): combo for combo in candidates}.values())


def multi_lang_name(eng_name, cjk_name):
    if eng_name and cjk_name:
        return "{} ({})".format(eng_name, cjk_name)
    else:
        return eng_name or cjk_name


def comparison_type_check(obj, other, req_type, op):
    if not isinstance(other, req_type):
        fmt = "{!r} is not supported between instances of {!r} and {!r}"
        raise TypeError(fmt.format(op, type(obj).__name__, type(other).__name__))


def expanded_wiki_table(table_ele):
    """
    In a table containing multiple cells that span multiple rows in a given column, it can be difficult to determine the
    value in that column for an arbitrary row.  This function expands those row-spanning cells to duplicate their values
    in each row that they visually appear in.

    :param table_ele: A bs4 <table> element
    :return list: A list of rows as lists of tr children elements
    """
    rows = []
    row_spans = []
    for tr in table_ele.find_all("tr"):
        eles = [tx for tx in tr.children if not isinstance(tx, NavigableString)]
        # log.debug("{} => ({}) {}".format(tr, len(eles), eles), extra={"color": "cyan"})
        if all(ele.name == "th" for ele in eles) or len(eles) == 1:
            continue
        elif not row_spans:  # 1st row
            row_spans = [(int(ele.get("rowspan") or 0) - 1, ele) for ele in eles]
            row = eles
        else:
            # log.debug("spans ({}): {}".format(len(row_spans), row_spans), extra={"color": 13})
            row = []
            # ele_iter = iter(eles)
            for i, (col_rows_left, spanned_ele) in enumerate(list(row_spans)):
                if col_rows_left < 1:
                    ele = eles.pop(0)
                    colspan = int(ele.get("colspan", 0))
                    if colspan:
                        ele["colspan"] = colspan - 1
                        eles.insert(0, ele)
                    # try:
                    #     ele = next(ele_iter)
                    # except Exception as e:
                    #     log.error("[{}] Error getting next ele: {}".format(i, e), extra={"color": "red"})
                    #     raise e
                    row_spans[i] = (int(ele.get("rowspan") or 0) - 1, ele)
                    row.append(ele)
                else:
                    row_spans[i] = (col_rows_left - 1, spanned_ele)
                    row.append(spanned_ele)
        rows.append(row)
    return rows


def parse_discography_page(uri_path, clean_soup, artist):
    albums, singles = [], []
    try:
        date_comment_rx = parse_discography_page._date_comment_rx
    except AttributeError:
        date_comment_rx = parse_discography_page._date_comment_rx = re.compile(r"^(\S+ \d+\s*, \d{4}).*")

    for h2 in clean_soup.find_all("h2"):
        album_type = h2.text.strip().lower()
        sub_type = None
        if album_type in ("music videos", "see also"):
            break

        ele = h2.next_sibling
        while ele.name != "h2":
            if isinstance(ele, NavigableString):
                ele = ele.next_sibling
                continue
            elif ele.name == "h3":
                sub_type = ele.text.strip().lower()
            elif ele.name == "table":
                columns = [th.text.strip() for th in ele.find("tr").find_all("th")]
                if columns[-1] == "Album":
                    tracks = []
                    for row in expanded_wiki_table(ele):
                        title_ele = row[0]
                        album_ele = row[-1]
                        album_title = album_ele.text.strip()
                        if album_title.lower() == "non-album single":
                            album_title = None
                        links = link_tuples(chain(title_ele.find_all("a"), album_ele.find_all("a")))
                        track = parse_track_info(
                            1, title_ele.text, uri_path,
                            include={"links": links, "album": album_title, "year": int(row[1].text.strip())}
                        )
                        tracks.append(track)
                    singles.append({"type": album_type, "sub_type": sub_type, "tracks": tracks})
                else:
                    for i, th in enumerate(ele.find_all("th", scope="row")):
                        links = [(a.text, a.get("href") or "") for a in th.find_all("a")]
                        title = th.text.strip()
                        album = {
                            "title": title, "links": links, "type": album_type, "sub_type": sub_type, "is_ost": False,
                            "primary_artist": (artist.name, artist._uri_path), "uri_path": dict(links).get(title),
                            "base_type": album_type, "wiki": "en.wikipedia.org", "num": "{}{}".format(i, num_suffix(i)),
                            "collaborators": {}, "misc_info": [], "language": None, "is_feature_or_collab": None
                        }

                        for li in th.parent.find("td").find("ul").find_all("li"):
                            key, value = map(str.strip, li.text.split(":", 1))
                            key = key.lower()
                            if key == "released":
                                try:
                                    value = datetime_with_tz(value, "%B %d, %Y")
                                except Exception as e:
                                    m = date_comment_rx.match(value)
                                    if m:
                                        try:
                                            value = datetime_with_tz(m.group(1), "%B %d, %Y")
                                        except Exception:
                                            msg = "Unexpected date format on {}: {}".format(uri_path, value)
                                            raise WikiEntityParseException(msg) from e
                                    else:
                                        msg = "Unexpected date format on {}: {}".format(uri_path, value)
                                        raise WikiEntityParseException(msg) from e
                            elif key in ("label", "format"):
                                value = str2list(value, ",")

                            album[key] = value

                        try:
                            album["year"] = album["released"].year
                        except Exception as e:
                            pass
                        albums.append(album)
            ele = ele.next_sibling
    return albums, singles


if __name__ == "__main__":
    from ds_tools.logging import LogManager
    lm = LogManager.create_default_logger(2, log_path=None, entry_fmt="%(asctime)s %(name)s %(message)s")
