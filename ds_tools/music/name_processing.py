"""
:author: Doug Skrypa
"""

import logging
import os
import re
import types
from unicodedata import normalize, combining

from ..unicode import is_any_cjk, contains_any_cjk, is_hangul, LangCat
from ..utils import ParentheticalParser

__all__ = [
    'categorize_langs', 'combine_name_parts', 'eng_cjk_sort', 'fuzz_process', 'has_parens', 'parse_name', 'split_name',
    'str2list'
]
log = logging.getLogger(__name__)


def fuzz_process(text):
    """
    Performs the same functions as :func:`full_process<fuzzywuzzy.utils.full_process>`, with some additional steps.
    Consecutive spaces are condensed, and diacritical marks are stripped.  Example::\n
        >>> fuzz_process('Rosé  한')     # Note: there are 2 spaces here
        'rose 한'

    :param str text: A string to be processed
    :return str: The processed string
    """
    try:
        non_letter_non_num_rx = fuzz_process._non_letter_non_num_rx
    except AttributeError:
        non_letter_non_num_rx = fuzz_process._non_letter_non_num_rx = re.compile(r'\W')

    original = text
    text = non_letter_non_num_rx.sub(' ', text)     # Convert non-letter/numeric characters to spaces
    text = ' '.join(text.split())                   # Condense sets of consecutive spaces to 1 space (faster than regex)
    text = text.lower().strip()                     # Convert to lower case & strip leading/trailing whitespace
    if len(text) == 0:
        text = ' '.join(original.split()).lower().strip()   # In case the text is only non-letter/numeric characters
    # Remove accents and other diacritical marks; composed Hangul and the like stays intact
    text = normalize('NFC', ''.join(c for c in normalize('NFD', text) if not combining(c)))
    return text


def parse_name(text):
    """

    :param text:
    :return tuple: (base, cjk, stylized, aka, info)
    """
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

    lc_details = details.lower()
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
    elif lc_details.endswith('ost') and base.lower().endswith('ost') and contains_any_cjk(details):
        eng, cjk = eng_cjk_sort((base, details), permissive=True)
        return eng, cjk, None, None, None
    elif base.endswith(')') and details.endswith(')'):
        base_parts = parser.parse(base)
        details_parts = parser.parse(details)
        if len(base_parts) == len(details_parts) == 2 and base_parts[1] == details_parts[1]:
            eng, cjk = eng_cjk_sort((base_parts[0], details_parts[0]), permissive=True)
            return eng, cjk, None, None, [base_parts[1]]
    elif lc_details.startswith('hangul'):
        details = details[6:]
        if details.startswith(':'):
            details = details[1:].strip()

    # log.debug('base={!r}, details={!r}, processing further...'.format(base, details))
    cjk = ''
    found_hangul = False
    stylized = None
    aka = None
    aka_leads = ('aka', 'a.k.a.', 'also known as', 'or simply')
    info = []
    for part in map(str.strip, re.split('[;,]', details)):
        # log.debug('Processing part of details: {!r}'.format(part))
        lc_part = part.lower()
        if lc_part.startswith('stylized as'):
            stylized = part[11:].strip()
        elif is_any_cjk(part) and not found_hangul:
            found_hangul = is_hangul(part)
            cjk = part
        elif ':' in part and not found_hangul:
            _lang_name, cjk = eng_cjk_sort(tuple(map(str.strip, part.split(':', 1))))
            found_hangul = is_hangul(cjk)
        elif not found_hangul and not cjk and contains_any_cjk(part):
            part_parts = part.split()
            if is_hangul(part_parts[0]) and LangCat.categorize(part_parts[1]) == LangCat.ENG:
                prefix = os.path.commonprefix([base, part_parts[1]])
                if len(prefix) > 3 and prefix != base:  # Special case for EXO-CBX, slightly genericized
                    # log.debug('Matched split mixed part: {}'.format(part_parts))
                    found_hangul = True
                    cjk = part_parts[0]
                    info.append(part_parts[1])
                else:
                    found_hangul = LangCat.HAN in LangCat.categorize(part, True)
                    cjk = part
            else:
                found_hangul = LangCat.HAN in LangCat.categorize(part, True)
                cjk = part
        elif lc_part.endswith((' ver.', ' ver')):
            info.append(part)
        elif not aka:
            for lead in aka_leads:
                if lc_part.startswith(lead):
                    aka = part[len(lead):].strip()
                    break

    return base, cjk, stylized, aka, info


def is_unzipped_name(text):
    outer_commas, inner_commas = 0, 0
    in_parenthetical = 0
    for c in text:
        if c == ',':
            if in_parenthetical:
                inner_commas += 1
            else:
                outer_commas += 1
        elif c == '(':
            in_parenthetical += 1
        elif c == ')':
            in_parenthetical -= 1
    return outer_commas == inner_commas and outer_commas != 0


def split_names(text):
    if not any(c in text for c in ',&'):
        try:
            return [split_name(text, True)]
        except ValueError as e:
            if 'feat. ' in text:
                parser = ParentheticalParser()
                return [split_name(part, True, permissive=True) for part in parser.parse(text)]
            elif LangCat.categorize(text) == LangCat.MIX and has_parens(text):
                return [split_name(text, True, require_preceder=False)]
            else:
                raise e
    elif is_unzipped_name(text):
        parts = ParentheticalParser().parse(text)
        if len(parts) == 2:
            x, y = parts
        elif len(parts) == 3:
            if ',' in parts[0] and ',' in parts[2] and ',' not in parts[1]:
                x = '{} ({})'.format(*parts[:2])
                y = parts[2]
            else:
                raise ValueError('Unexpected parse result: {}'.format(parts))
        else:
            raise ValueError('Unexpected parse result: {}'.format(parts))
        return [split_name((a, b), True) for a, b in zip(map(str.strip, x.split(',')), map(str.strip, y.split(',')))]

    names = str2list(text)
    if any('(' in name and ')' not in name for name in names) or any(')' in name and '(' not in name for name in names):
        for i, name in enumerate(names):
            if i and ')' in name and '(' not in name:
                last = names[i - 1]
                if '(' in last and ')' not in last:
                    a, b = map(str.strip, last.split('('))
                    names[i - 1] = '{} / {}'.format(a, b)
                    names[i] = '{} / {}'.format(a, name[:-1] if name.endswith(')') else name)

    unique = []         # Maintain the order that they were in the original string
    for name in names:
        if name not in unique:
            unique.append(name)

    unique_split = []
    for name in unique:
        eng, cjk, of_group = split_name(name, True, permissive=True)
        unique_split.append((eng, cjk, of_group))
    return unique_split


def split_name(name, unused=False, check_keywords=True, permissive=False, require_preceder=True):
    """
    :param str|tuple name: A song/album/artist title
    :param bool unused: Return a 3-tuple instead of a 2-tuple, with the 3rd element being the content that was discarded
    :param bool check_keywords: Check for some key words at the start of the English name, such as 'inst.' or 'feat.'
      and count that as an invalid English name part
    :return tuple: (english, cjk)
    """
    parser = ParentheticalParser(require_preceder=require_preceder)
    if isinstance(name, str):
        name = name.strip()
        try:
            parts = parser.parse(name)   # Note: returned strs already stripped of leading/trailing spaces
        except Exception as e:
            raise ValueError('Unable to split {!r} into separate English/CJK strings'.format(name)) from e
    else:
        parts = name

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
            if ' / ' in eng:                                # Group / Soloist (soloist other lang)
                not_used, eng = eng.split(' / ')
            if ' / ' in cjk:
                _nu, cjk = cjk.split(' / ')
                not_used = (not_used, _nu) if not_used else _nu
            elif not not_used and ' (' in eng and ' (' in cjk:  # Soloist (group) (Soloist (group) {other lang})
                eng, g_eng = parser.parse(eng)
                cjk, g_cjk = parser.parse(cjk)
                not_used = (g_eng, g_cjk)
        elif permissive and LangCat.MIX not in langs and len(set(langs)) == 1:
            eng, cjk = eng_cjk_sort(parts[0])               # Soloist (Group) {all same lang}
            not_used = parts[1]
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
        elif langs == (LangCat.ENG, LangCat.MIX):
            common_suffix = ''.join(reversed(os.path.commonprefix(list(map(lambda x: ''.join(reversed(x)), parts)))))
            if len(common_suffix) > 3 and LangCat.categorize(parts[1], True).intersection(LangCat.asian_cats):
                eng, cjk = parts
            elif ' / ' in parts[1]:                         # Soloist (Group / soloist other lang)
                try:
                    not_used, cjk = eng_cjk_sort(parts[1].split(' / '))
                except Exception:
                    pass
                else:
                    eng = parts[0]
        elif langs == (LangCat.MIX, LangCat.MIX) and ' X ' in parts[1]:
            if LangCat.categorize(parts[0], True).intersection(LangCat.asian_cats):
                eng, cjk = '', parts[0]
            else:
                eng, cjk = parts[0], ''
            not_used = parts[1].split(' X ')
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
                keyword = next((val for val in ('from ',) if not_used.startswith(val)), None)
                if keyword:
                    not_used = not_used[len(keyword):].strip()

    if not eng and not cjk:
        # traceback.print_stack()
        fmt = 'Unable to split {!r} into separate English/CJK strings - parts={}, langs={}'
        raise ValueError(fmt.format(name, parts, langs))

    if check_keywords:
        keywords = ('feat.', 'featuring', 'inst.', 'instrumental')
        lc_eng = eng.lower()
        if lc_eng.startswith(keywords):
            if not cjk and not not_used:
                keyword = next((val for val in keywords if val in lc_eng), None)
                if keyword:
                    eng = eng[len(keyword):].strip()
            else:
                log.debug('Shuffling return values due to keywords: {}'.format((eng, cjk, not_used)))
                if not_used is None:
                    not_used = eng
                elif isinstance(not_used, str):
                    not_used = [not_used, eng]
                else:
                    not_used = list(not_used)
                    not_used.append(eng)
                eng = ''

            if not cjk and not eng:
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
            return tuple(reversed(strs))
    elif isinstance(strs, str):
        if langs in (LangCat.ENG, LangCat.NUL):
            return strs, ''
        elif langs in LangCat.non_eng_cats:
            return '', strs
        elif langs == LangCat.MIX:
            detailed = LangCat.categorize(strs, True)
            if isinstance(detailed, set) and not detailed.intersection(LangCat.asian_cats):
                return strs, ''

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
