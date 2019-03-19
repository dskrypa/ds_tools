"""
:author: Doug Skrypa
"""

import logging
import re
from collections import OrderedDict
from itertools import chain, combinations

from ...utils import QMARKS

__all__ = [
    'comparison_type_check', 'edition_combinations', 'get_page_category', 'multi_lang_name', 'sanitize_path',
    'synonym_pattern'
]
log = logging.getLogger(__name__)

FEAT_ARTIST_INDICATORS = ("with", "feat.", "feat ", "featuring")
NUM_STRIP_TBL = str.maketrans({c: "" for c in "0123456789"})
NUMS = {
    "first": "1st", "second": "2nd", "third": "3rd", "fourth": "4th", "fifth": "5th", "sixth": "6th",
    "seventh": "7th", "eighth": "8th", "ninth": "9th", "tenth": "10th", "debut": "1st"
}
PAGE_CATEGORIES = OrderedDict([
    ("album", ("albums", "discography article stubs")),
    ("group", ("groups", "group article stubs")),
    ("singer", ("singers", "person article stubs")),
    ("soundtrack", ("osts", "kost", "jost", "cost")),
    ("tv_series", ("television series", "television drama", "kdrama", "competition shows")),
    ("discography", ("discographies",)),
    ("disambiguation", ("disambiguation",)),
    ("agency", ("agencies",)),
    ("sports team", ("sports team",)),
])
PATH_SANITIZATION_DICT = {c: "" for c in "*;?<>\""}
PATH_SANITIZATION_DICT.update({"/": "_", ":": "-", "\\": "_", "|": "-"})
PATH_SANITIZATION_TABLE = str.maketrans(PATH_SANITIZATION_DICT)
QMARK_STRIP_TBL = str.maketrans({c: "" for c in QMARKS})
REGEX_ESCAPE_TABLE = str.maketrans({c: "\\" + c for c in "()[]{}^$+*.?|\\"})
SYNONYM_SETS = [{"and", "&", "+"}, {"version", "ver."}]


def sanitize_path(text):
    return text.translate(PATH_SANITIZATION_TABLE)


def comparison_type_check(obj, other, req_type, op):
    if not isinstance(other, req_type):
        fmt = "{!r} is not supported between instances of {!r} and {!r}"
        raise TypeError(fmt.format(op, type(obj).__name__, type(other).__name__))


def multi_lang_name(eng_name, cjk_name):
    if eng_name and cjk_name:
        return "{} ({})".format(eng_name, cjk_name)
    else:
        return eng_name or cjk_name


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


def synonym_pattern(text, synonym_sets=None, chain_sets=True):
    """
    :param str text: Text from which a regex pattern should be generated
    :param synonym_sets: Iterable that yields sets of synonym strings, or None to use :data:`SYNONYM_SETS`
    :param bool chain_sets: Chain the given synonym_sets with :data:`SYNONYM_SETS` (if False: only consider the provided
      synonym_sets)
    :return: Compiled regex pattern for the given text that will match the provided synonyms
    """
    parts = [part.translate(REGEX_ESCAPE_TABLE) for part in re.split("(\W)", re.sub('\s+', ' ', text.lower())) if part]
    synonym_sets = chain(SYNONYM_SETS, synonym_sets) if chain_sets and synonym_sets else synonym_sets or SYNONYM_SETS

    for synonym_set in synonym_sets:
        for i, part in enumerate(list(parts)):
            if part in synonym_set:
                parts[i] = "(?:{})".format("|".join(s.translate(REGEX_ESCAPE_TABLE) for s in sorted(synonym_set)))

    pattern = ''.join('\s+' if part == ' ' else part for part in parts)
    # log.debug("Synonym pattern: {!r} => {!r}".format(text, pattern))
    return re.compile(pattern, re.IGNORECASE)


def get_page_category(url, cats):
    if url.endswith('_discography'):
        return 'discography'
    elif any(i in cat for i in ("singles", "songs") for cat in cats):
        if any("single album" in cat for cat in cats):
            return "album"
        else:
            return "collab/feature/single"
    else:
        for category, indicators in PAGE_CATEGORIES.items():
            if any(i in cat for i in indicators for cat in cats):
                return category

        log.debug("Unable to determine category for {}".format(url))
        return None
