"""
:author: Doug Skrypa
"""

import logging
import re
from itertools import chain, combinations

# import Levenshtein as lev
from fuzzywuzzy import utils as fuzz_utils

from ...utils import QMARKS

__all__ = ['comparison_type_check', 'edition_combinations', 'multi_lang_name', 'synonym_pattern']
log = logging.getLogger(__name__)

FEAT_ARTIST_INDICATORS = ("with", "feat.", "feat ", "featuring")
NUM_STRIP_TBL = str.maketrans({c: "" for c in "0123456789"})
NUMS = {
    "first": "1st", "second": "2nd", "third": "3rd", "fourth": "4th", "fifth": "5th", "sixth": "6th",
    "seventh": "7th", "eighth": "8th", "ninth": "9th", "tenth": "10th", "debut": "1st"
}
PATH_SANITIZATION_DICT = {c: "" for c in "*;?<>\""}
PATH_SANITIZATION_DICT.update({"/": "_", ":": "-", "\\": "_", "|": "-"})
PATH_SANITIZATION_TABLE = str.maketrans(PATH_SANITIZATION_DICT)
QMARK_STRIP_TBL = str.maketrans({c: "" for c in QMARKS})
SYNONYMS = [{"and": "and", "&": "&", "+": "\\+"}]


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


def synonym_pattern(name):
    parts = name.lower().split()
    for synonym_set in SYNONYMS:
        for i, part in enumerate(list(parts)):
            if part in synonym_set:
                parts[i] = "(?:{})".format("|".join(synonym_set.values()))

    pattern = r"\s+".join(parts)
    # log.debug("Synonym pattern: {!r} => {!r}".format(name, pattern))
    return re.compile(pattern, re.IGNORECASE)
