"""
:author: Doug Skrypa
"""

import logging
import re
from collections import OrderedDict
from itertools import chain, combinations
from urllib.parse import urlparse

from ...utils import QMARKS, soupify, regexcape

__all__ = [
    'comparison_type_check', 'edition_combinations', 'get_page_category', 'multi_lang_name', 'normalize_href',
    'sanitize_path', 'strify_collabs', 'synonym_pattern'
]
log = logging.getLogger(__name__)

FEAT_ARTIST_INDICATORS = ('with', 'feat.', 'feat ', 'featuring')
NUM_STRIP_TBL = str.maketrans({c: '' for c in '0123456789'})
NUMS = {
    'first': '1st', 'second': '2nd', 'third': '3rd', 'fourth': '4th', 'fifth': '5th', 'sixth': '6th',
    'seventh': '7th', 'eighth': '8th', 'ninth': '9th', 'tenth': '10th', 'debut': '1st'
}
PAGE_CATEGORIES = OrderedDict([
    ('album', ('albums', 'discography article stubs', ' eps')),     # Note: space in ' eps' is intentional
    ('group', ('group', 'group article stubs', 'bands', 'duos')),
    ('singer', ('singer', 'person article stubs', 'actor', 'actress', 'musician', 'rapper')),
    ('soundtrack', ('osts', 'kost', 'jost', 'cost')),
    ('competition_or_show', ('competition', 'variety show', 'variety television')),
    ('tv_series', ('television series', 'drama', 'competition shows')),
    ('discography', ('discographies',)),
    ('disambiguation', ('disambiguation', 'ambiguous')),
    ('agency', ('agencies',)),
    ('sports team', ('sports team',)),
    ('movie', ('movies', 'films')),
    ('play', ('plays',)),
    ('characters', ('fictional characters', 'film characters')),
    ('filmography', ('filmographies',)),
    ('misc', (
        'games', 'comics', 'deities', 'television seasons', 'appliances', 'standards', 'military', 'amusement',
        'episodes', 'hobbies', 'astronauts', 'war', 'economics', 'disasters', 'events', 'bugs', 'modules', 'elves',
        'dwarves', 'orcs', 'lists', 'twost', 'food', 'alcohol', 'pubs', 'geography', 'towns', 'cities', 'countries',
        'counties', 'landmark', 'lake', 'ocean', 'forest', 'roads'
    )),
])
PATH_SANITIZATION_DICT = {c: '' for c in '*;?<>"'}
PATH_SANITIZATION_DICT.update({'/': '_', ':': '-', '\\': '_', '|': '-'})
PATH_SANITIZATION_TABLE = str.maketrans(PATH_SANITIZATION_DICT)
QMARK_STRIP_TBL = str.maketrans({c: '' for c in QMARKS})
SYNONYM_SETS = [{'and', '&', '+'}, {'version', 'ver.'}]


def normalize_href(href):
    if not href:
        return None
    href = href[6:] if href.startswith('/wiki/') else href
    return None if 'redlink=1' in href else href


def sanitize_path(text):
    return text.translate(PATH_SANITIZATION_TABLE)


def comparison_type_check(obj, other, req_type, op):
    if not isinstance(other, req_type):
        fmt = '{!r} is not supported between instances of {!r} and {!r}'
        raise TypeError(fmt.format(op, type(obj).__name__, type(other).__name__))


def multi_lang_name(eng_name, cjk_name):
    if eng_name and cjk_name:
        if cjk_name.startswith('(') and cjk_name.endswith(')'):
            return '{} {}'.format(eng_name, cjk_name)
        return '{} ({})'.format(eng_name, cjk_name)
    else:
        return eng_name or cjk_name


def edition_combinations(editions, next_track):
    next_track -= 1
    candidates = []
    for i in range(len(editions)):
        for combo in combinations(editions, i):
            tracks = sorted(t['num'] for t in chain.from_iterable(edition['tracks'] for edition in combo))
            if tracks and len(set(tracks)) == len(tracks) == max(tracks) == next_track and min(tracks) == 1:
                candidates.append(combo)

    if not candidates:
        for edition in editions:
            tracks = sorted(t['num'] for t in edition['tracks'])
            if tracks and len(set(tracks)) == len(tracks) == max(tracks) == next_track and min(tracks) == 1:
                candidates.append([edition])

    return list({tuple(e.get('section') or '' for e in combo): combo for combo in candidates}.values())


def synonym_pattern(text, synonym_sets=None, chain_sets=True):
    """
    :param str text: Text from which a regex pattern should be generated
    :param synonym_sets: Iterable that yields sets of synonym strings, or None to use :data:`SYNONYM_SETS`
    :param bool chain_sets: Chain the given synonym_sets with :data:`SYNONYM_SETS` (if False: only consider the provided
      synonym_sets)
    :return: Compiled regex pattern for the given text that will match the provided synonyms
    """
    parts = [regexcape(part) for part in re.split('(\W)', re.sub('\s+', ' ', text.lower())) if part]
    synonym_sets = chain(SYNONYM_SETS, synonym_sets) if chain_sets and synonym_sets else synonym_sets or SYNONYM_SETS

    for synonym_set in synonym_sets:
        for i, part in enumerate(list(parts)):
            if part in synonym_set:
                parts[i] = '(?:{})'.format('|'.join(regexcape(s) for s in sorted(synonym_set)))

    pattern = ''.join('\s+' if part == ' ' else part for part in parts)
    # log.debug('Synonym pattern: {!r} => {!r}'.format(text, pattern))
    return re.compile(pattern, re.IGNORECASE)


def get_page_category(url, cats, no_debug=False, raw=None):
    if url.endswith('_discography'):
        return 'discography'
    elif any(i in cat for i in ('singles', 'songs') for cat in cats):
        if any('single album' in cat for cat in cats):
            return 'album'
        else:
            return 'collab/feature/single'
    else:
        to_return = None
        for category, indicators in PAGE_CATEGORIES.items():
            if any(i in cat for i in indicators for cat in cats):
                to_return = category
                break

        if to_return == 'soundtrack':
            uri_path = urlparse(url).path
            uri_path = uri_path[6:] if uri_path.startswith('/wiki/') else uri_path
            if uri_path.count('/') > 1 and raw and 'Lyrics' in raw:
                expected = uri_path.rsplit('/', 1)[0]
                for a in soupify(raw).find_all('a'):
                    if a.get('href') == expected:
                        return 'lyrics'
        elif to_return == 'tv_series' and any(val in cats for val in ('banjun drama', 'lists')):
            return 'misc'

        if to_return:
            return to_return

        if '/wiki/Template:' in url:
            return 'template'

        if not no_debug:
            log.debug('Unable to determine category for {}'.format(url))
        return None


def strify_collabs(collaborators):
    collabs = []
    for c in collaborators:
        if isinstance(c, dict):
            a_name = '{} ({})'.format(*c['artist']) if c['artist'][1] else c['artist'][0]
            if 'of_group' in c:
                g_name = '{} ({})'.format(*c['of_group']) if c['of_group'][1] else c['of_group'][0]
                collabs.append('{} of {}'.format(a_name, g_name))
            else:
                collabs.append(a_name)
        else:
            collabs.append(c)
    return sorted(set(collabs))
