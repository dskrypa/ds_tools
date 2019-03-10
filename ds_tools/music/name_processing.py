"""
:author: Doug Skrypa
"""

import logging
import re
import types
from enum import Enum

from ..unicode import is_any_cjk, contains_any_cjk, is_hangul, LangCat
from ..utils import ParentheticalParser

__all__ = [
    'categorize_langs', 'combine_name_parts', 'eng_cjk_sort', 'has_parens', 'parse_name', 'split_name', 'str2list'
]
log = logging.getLogger(__name__)


def parse_name(text):
    first_sentence = text.strip().partition('. ')[0].strip()  # Note: space is intentional
    first_sentence = first_sentence.replace('\xa0', ' ')
    parser = ParentheticalParser()
    try:
        parts = parser.parse(first_sentence)    # Note: returned strs already stripped of leading/trailing spaces
    except Exception as e:
        raise ValueError('Unable to parse artist name from intro: {}'.format(first_sentence)) from e

    # log.debug('{!r} => {}'.format(first_sentence, parts))
    if len(parts) == 1:
        base, details = parts[0], ''
    else:
        base, details = parts[:2]
    if ' is ' in base:
        base = base[:base.index(' is ')].strip()
        eng, cjk = eng_cjk_sort(base)
        return eng, cjk, None, None, None
    elif is_any_cjk(details):
        return base, details, None, None, None
    elif base in ('+ +', 'X X'):                            # Special case for particular albums
        return '[{}]'.format(base), '', None, details, None
    elif len(parts) == 2 and first_sentence.endswith('"'):  # Special case for album name ending in quoted word
        return '{} "{}"'.format(base, details), '', None, None, None
    elif not contains_any_cjk(details):
        eng, cjk = eng_cjk_sort(base)
        return eng, cjk, None, None, None
    elif details.lower().endswith('ost') and base.lower().endswith('ost') and contains_any_cjk(details):
        eng, cjk = eng_cjk_sort((base, details), permissive=True)
        return eng, cjk, None, None, None
    elif base.endswith(')') and details.endswith(')'):
        base_parts = parser.parse(base)
        details_parts = parser.parse(details)
        if len(base_parts) == len(details_parts) == 2 and base_parts[1] == details_parts[1]:
            eng, cjk = eng_cjk_sort((base_parts[0], details_parts[0]), permissive=True)
            return eng, cjk, None, None, [base_parts[1]]

    cjk = ''
    found_hangul = False
    stylized = None
    aka = None
    aka_leads = ('aka', 'a.k.a.', 'also known as', 'or simply')
    info = []
    for part in map(str.strip, re.split('[;,]', details)):
        lc_part = part.lower()
        if lc_part.startswith('stylized as'):
            stylized = part[11:].strip()
        elif is_any_cjk(part) and not found_hangul:
            found_hangul = is_hangul(part)
            cjk = part
        elif ':' in part and not found_hangul:
            _lang_name, cjk = eng_cjk_sort(tuple(map(str.strip, part.split(':', 1))))
            found_hangul = is_hangul(cjk)
        elif lc_part.endswith((' ver.', ' ver')):
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
        raise ValueError('Unable to split {!r} into separate English/CJK strings'.format(name)) from e

    if not parts:
        raise ValueError('Unable to split {!r} into separate English/CJK strings (nothing was parsed)'.format(name))

    eng, cjk, not_used = None, None, None
    langs = categorize_langs(parts)
    s = 's' if len(parts) > 1 else ''
    log.log(9, 'ParentheticalParser().parse({!r}) => {} part{}: {} ({})'.format(name, len(parts), s, parts, langs))
    if len(parts) == 1:
        try:
            eng, cjk = eng_cjk_sort(parts[0], langs[0])
        except ValueError as e:
            raise ValueError('Unable to split {!r} into separate English/CJK strings'.format(name)) from e
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
        raise ValueError('Unable to split {!r} into separate English/CJK strings'.format(name))

    if check_keywords and eng.lower().startswith(('feat.', 'featuring', 'inst.', 'instrumental')):
        log.debug('Shuffling return values due to keywords: {}'.format((eng, cjk, not_used)))
        if not_used is None:
            not_used = eng
        elif isinstance(not_used, str):
            not_used = [not_used, eng]
        else:
            not_used = list(not_used)
            not_used.append(eng)
        eng = ''
        if not cjk:
            raise ValueError('Unable to split {!r} into separate English/CJK strings'.format(name))

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

    if not isinstance(langs, LangCat) and len(langs) == 2:
        a, b = langs
        if a in (LangCat.ENG, LangCat.NUL) and (b in LangCat.non_eng_cats or permissive and b == LangCat.MIX):
            return strs
        elif b in (LangCat.ENG, LangCat.NUL) and (a in LangCat.non_eng_cats or permissive and a == LangCat.MIX):
            return reversed(strs)
    elif isinstance(strs, str):
        if langs in (LangCat.ENG, LangCat.NUL):
            return strs, ''
        elif langs in LangCat.non_eng_cats:
            return '', strs
    raise ValueError('Unexpected values: strs={!r}, langs={!r}'.format(strs, langs))


def has_parens(text):
    return any(c in text for c in '()[]')


def categorize_langs(strs):
    return tuple(LangCat.categorize(s) for s in strs)


def str2list(text, pat='^(?:with|feat\.?|as) | and |,|;|&| feat\.? | featuring | with '):
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


def combine_name_parts(name_parts):
    langs = categorize_langs(name_parts)
    last = None
    for i, lang in enumerate(langs):
        if lang == last:
            prefix = name_parts[:i-1]
            suffix = name_parts[i+1:]
            combined = '{} ({})'.format(*name_parts[i-1:i+1])
            return prefix + [combined] + suffix
        last = lang
    combined = '{} ({})'.format(*name_parts[:2])
    return [combined] + name_parts[2:]
