"""
:author: Doug Skrypa
"""

import logging
import os
import re
import types
from unicodedata import normalize, combining

from cachetools import LRUCache
from fuzzywuzzy import fuzz
from fuzzywuzzy.fuzz import _token_sort as fuzz_token_sort_ratio, _token_set as fuzz_token_set_ratio

from ..caching import cached
from ..unicode import is_any_cjk, contains_any_cjk, is_hangul, LangCat
from ..utils import ParentheticalParser, unsurround, normalize_roman_numerals, common_suffix, regexcape
from .exceptions import NameFormatError

__all__ = [
    'categorize_langs', 'combine_name_parts', 'eng_cjk_sort', 'fuzz_process', 'has_parens', 'parse_name',
    'revised_weighted_ratio', 'split_name', 'str2list'
]
log = logging.getLogger(__name__)


def fuzz_process(text, strip_special=True):
    """
    Performs the same functions as :func:`full_process<fuzzywuzzy.utils.full_process>`, with some additional steps.
    Consecutive spaces are condensed, and diacritical marks are stripped.  Example::\n
        >>> fuzz_process('Rosé  한')     # Note: there are 2 spaces here
        'rose 한'

    :param str text: A string to be processed
    :param bool strip_special: Strip special characters (defaults to True - set to False to preserve them)
    :return str: The processed string
    """
    if not text:
        return text
    try:
        non_letter_non_num_rx = fuzz_process._non_letter_non_num_rx
        ost_rx = fuzz_process._ost_rx
    except AttributeError:
        non_letter_non_num_rx = fuzz_process._non_letter_non_num_rx = re.compile(r'\W')
        ost_rx = fuzz_process._ost_rx = re.compile(r'\sOST(?:$|\s|\)|\])', re.IGNORECASE)

    original = text
    if strip_special:                               # Some titles are only differentiable by special characters
        text = non_letter_non_num_rx.sub(' ', text) # Convert non-letter/numeric characters to spaces
    text = ' '.join(text.split())                   # Condense sets of consecutive spaces to 1 space (faster than regex)
    text = ost_rx.sub('', text)                     # Remove 'OST' to prevent false positives based only on that
    text = text.lower().strip()                     # Convert to lower case & strip leading/trailing whitespace
    if len(text) == 0:
        text = ' '.join(original.split()).lower().strip()   # In case the text is only non-letter/numeric characters
    # Remove accents and other diacritical marks; composed Hangul and the like stays intact
    text = normalize('NFC', ''.join(c for c in normalize('NFD', text) if not combining(c)))
    return text


def revised_weighted_ratio(p1, p2):
    """
    Return a measure of the sequences' similarity between 0 and 100, using different algorithms.
    **Steps in the order they occur**

    #. Run full_process from utils on both strings
    #. Short circuit if this makes either string empty
    #. Take the ratio of the two processed strings (fuzz.ratio)
    #. Run checks to compare the length of the strings
        * If one of the strings is more than 1.5 times as long as the other use partial_ratio comparisons - scale
          partial results by 0.9 (this makes sure only full results can return 100)
        * If one of the strings is over 8 times as long as the other instead scale by 0.6
    #. Run the other ratio functions
        * if using partial ratio functions call partial_ratio, partial_token_sort_ratio and partial_token_set_ratio
          scale all of these by the ratio based on length
        * otherwise call token_sort_ratio and token_set_ratio
        * all token based comparisons are scaled by 0.95 (on top of any partial scalars)
    #. Take the highest value from these results round it and return it as an integer.
    """
    if not p1 or not p2:
        return 0
    elif p1 == p2:
        return 100

    base = fuzz.ratio(p1, p2)
    lens = (len(p1), len(p2))
    len_ratio = max(lens) / min(lens)
    # if strings are similar length, don't use partials
    try_partial = len_ratio >= 1.5

    # Defaults:
    # fuzz_token_sort_ratio(s1, s2, partial=True, force_ascii=True, full_process=True)
    # fuzz_token_set_ratio(s1, s2, partial=True, force_ascii=True, full_process=True)

    if try_partial:
        # if one string is much much shorter than the other
        if len_ratio > 3:
            partial_scale = .25
        elif len_ratio > 2:
            partial_scale = .45
        elif len_ratio > 1.5:
            partial_scale = .625
        elif len_ratio > 1:
            partial_scale = .75
        else:
            partial_scale = .90

        partial = fuzz.partial_ratio(p1, p2) * partial_scale
        ptsor = fuzz_token_sort_ratio(p1, p2, True, False, False) * .95 * partial_scale
        # ptsor = fuzz.partial_token_sort_ratio(p1, p2, full_process=False) * .95 * partial_scale
        ptser = fuzz_token_set_ratio(p1, p2, True, False, False) * .95 * partial_scale
        # ptser = fuzz.partial_token_set_ratio(p1, p2, full_process=False) * .95 * partial_scale
        # log.debug('{!r}=?={!r}: ratio={}, len_ratio={}, part_ratio={}, tok_sort_ratio={}, tok_set_ratio={}'.format(p1, p2, base, len_ratio, partial, ptsor, ptser))
        return int(round(max(base, partial, ptsor, ptser)))
    else:
        tsor = fuzz_token_sort_ratio(p1, p2, False, False, False) * .95
        # tsor = fuzz.token_sort_ratio(p1, p2, full_process=False) * .95
        tser = fuzz_token_set_ratio(p1, p2, False, False, False) * .95
        # tser = fuzz.token_set_ratio(p1, p2, full_process=False) * .95
        # log.debug('{!r}=?={!r}: ratio={}, len_ratio={}, tok_sort_ratio={}, tok_set_ratio={}'.format(p1, p2, base, len_ratio, tsor, tser))
        return int(round(max(base, tsor, tser)))


def parse_name(text):
    """

    :param text:
    :return tuple: (base, cjk, stylized, aka, info)
    """
    stripped = text.strip()
    first_sentence, period, stripped = stripped.partition('. ')     # Note: space is intentional
    if (' ' not in first_sentence) or (first_sentence.count('"') == 1 and stripped.count('"') % 2 == 1):
        first_sentence += period + stripped.partition('. ')[0].strip()
    first_sentence = normalize_roman_numerals(first_sentence.replace('\xa0', ' '))
    if first_sentence.startswith('"') and first_sentence.endswith('"') and first_sentence.count('"') == 2:
        first_sentence = unsurround(first_sentence)
    parser = ParentheticalParser()
    try:
        parts = parser.parse(first_sentence)    # Note: returned strs already stripped of leading/trailing spaces
    except Exception as e:
        raise NameFormatError('Unable to parse artist name from intro: {}'.format(first_sentence)) from e

    # log.debug('{!r} => {}'.format(first_sentence, parts))
    if len(parts) == 1:
        base, details = parts[0], ''
    else:
        base, details = parts[:2]
        if any(val in details for val in ('professionally known as', 'better known by')) and len(parts) > 2:
            if parts[2].startswith('('):
                details = ' '.join(parts[1:3])
            elif parts[2].startswith('Hangul'):
                details = '{} ({})'.format(details, parts[2])

    lc_details = details.lower()
    if ' is a ' in base:
        base = base[:base.index(' is a ')].strip()
        # log.warning('Used \'is\' split for {!r}=>{!r}==>>{!r}'.format(text[:250], parts[0], base), extra={'color': (9, 11)})
        eng, cjk = eng_cjk_sort(base)
        return eng, cjk, None, [], None
    elif is_any_cjk(details):
        return base, details, None, [], None
    elif base in ('+ +', 'X X'):                            # Special case for particular albums
        return '[{}]'.format(base), '', None, details, None
    elif len(parts) == 2 and first_sentence.endswith('"'):  # Special case for album name ending in quoted word
        return '{} "{}"'.format(base, details), '', None, [], None
    elif not contains_any_cjk(details):
        eng, cjk = eng_cjk_sort(base)
        return eng, cjk, None, [], None
    elif lc_details.endswith('ost') and base.lower().endswith('ost') and contains_any_cjk(details):
        eng, cjk = eng_cjk_sort((base, details), permissive=True)
        return eng, cjk, None, [], None
    elif base.endswith(')') and details.endswith(')'):
        base_parts = parser.parse(base)
        details_parts = parser.parse(details)
        if len(base_parts) == len(details_parts) == 2 and base_parts[1] == details_parts[1]:
            eng, cjk = eng_cjk_sort((base_parts[0], details_parts[0]), permissive=True)
            return eng, cjk, None, [], [base_parts[1]]
    # elif lc_details.startswith('hangul'):
    #     details = details[6:]
    #     if details.startswith(':'):
    #         details = details[1:].strip()

    try:
        dob_rx = parse_name._dob_rx
        year_rx = parse_name._year_rx
        aka_rx = parse_name._aka_rx
    except AttributeError:
        year_rx = parse_name._year_rx = re.compile(r'\d{4}\)?')
        dob_rx = parse_name._dob_rx = re.compile(
            r'born (?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\S* \d+', re.IGNORECASE
        )
        aka_pat_parts = [
            r'(?:also|better|previously|formerly|professionally) (?:known|written) \S*\s*as',
            r'(?:also|better|previously|formerly|professionally) known by (?:the|her|his) \S*\s*names?',
            r'a\.?k\.?a\.?', r'or simply', r'an acronym for', r'short for', r'(?:or|born) ',
        ]
        aka_rx = parse_name._aka_rx = re.compile(r'^({})(.*)$'.format('|'.join(aka_pat_parts)), re.IGNORECASE)

    # log.debug('base={!r}, details={!r}, processing further...'.format(base, details))
    cjk = ''
    found_hangul = False
    stylized = None
    aka = []
    next_is_aka = False
    style_leads = ('stylized as', 'sometimes styled as', 'sometimes stylized as')
    info = []
    details_parts = list(map(str.strip, re.split('[;,]', details)))
    while details_parts:
        part = details_parts.pop(0)
        # log.debug('Processing part of details: {!r}'.format(part))
        lc_part = part.lower()
        if next_is_aka:
            if ':' in part:
                # log.debug('Processing aka section with colon: {!r}'.format(part))
                try:
                    aka_eng, aka_cjk = split_name(part)         # if 'eng (lang: value)', split_name removes lang name
                except ValueError:
                    aka.append(part)
                else:
                    aka.append('{} ({})'.format(aka_eng, aka_cjk))
            else:
                # log.debug('Processing aka section: {!r}'.format(part))
                aka.append(part)
            next_is_aka = False
        elif any(lead for lead in style_leads if lc_part.startswith(lead)):
            style_lead = next((lead for lead in style_leads if lc_part.startswith(lead)), None)
            stylized = part[len(style_lead):].strip()
            if 'and also abbreviated' in stylized:
                stylized = stylized.partition('and also abbreviated')[0].strip()
        elif is_any_cjk(part) and not found_hangul:
            found_hangul = is_hangul(part)
            cjk = part
        elif lc_part.endswith((' ver.', ' ver')):
            info.append(part)
        elif dob_rx.match(part):
            pass
        elif aka_rx.match(part):
            _orig = part
            m = aka_rx.match(part)
            # log.debug('AKA match: {!r} => {} [remaining: {}]'.format(_orig, m.groups(), details_parts))
            part = m.group(2).strip()
            reset_cjk = False
            if not found_hangul and not cjk and contains_any_cjk(part) and has_parens(part):
                _aka, part = map(str.strip, part.split())
                details_parts.insert(0, unsurround(part))
            elif has_parens(part):
                _parts = ParentheticalParser().parse(part)
                if len(_parts) == 2:
                    _aka = _parts[0]
                    details_parts.insert(0, _parts[1])
                else:
                    err_msg = 'Unexpected AKA format for part={!r}'.format(_orig)
                    raise NameFormatError(err_msg + _parse_dbg(base, cjk, stylized, aka, info, details_parts))
            else:
                _aka = part

            aka_intro = m.group(1)
            if details_parts and any(val in aka_intro for val in ('better', 'professionally', 'stage')):
                if LangCat.contains_any(details_parts[0], LangCat.asian) or 'stage' in aka_intro:
                    _aka, base = base, _aka
                    reset_cjk = bool(cjk)

            aka.append(_aka)
            if reset_cjk:
                aka.append(cjk)
                cjk = '' if 'stage' in aka_intro else None
            next_is_aka = not _aka
            if next_is_aka:
                log.log(9, 'Next part is AKA value because part={!r} has no aka value'.format(_orig))
        elif ':' in part and contains_any_cjk(part):
            try:
                pronounced_rx = parse_name._pronounced_rx
            except AttributeError:
                pronounced_rx = parse_name._pronounced_rx = re.compile(r'(pronounced ".*")\s+(\S:.*)', re.IGNORECASE)

            m = pronounced_rx.match(part)
            if m:
                info.extend(m.groups())
            else:
                _lang_name, alt_lang_val = tuple(map(str.strip, part.split(':', 1)))
                langs = categorize_langs((_lang_name, alt_lang_val))
                if langs[1] == LangCat.MIX and ' on ' in alt_lang_val:
                    alt_lang_val, _dob = map(str.strip, alt_lang_val.split(' on ', 1))
                    langs = (langs[0], LangCat.categorize(alt_lang_val))

                if langs[0] != LangCat.ENG:
                    err_msg = 'Unexpected langs={} for \'lang: value\' part={!r}'.format(langs, part)
                    raise NameFormatError(err_msg + _parse_dbg(base, cjk, stylized, aka, info, details_parts))
                elif langs[1] == LangCat.MIX:
                    suffix = common_suffix((base, alt_lang_val))
                    if not suffix or LangCat.categorize(alt_lang_val[:-len(suffix)]) not in LangCat.asian_cats:
                        if 'pronounced' in alt_lang_val:
                            _split = tuple(map(str.strip, alt_lang_val.partition('pronounced')))
                            part_0_lang = LangCat.categorize(_split[0])
                            if part_0_lang in LangCat.asian_cats:
                                cjk = _split[0]
                                found_hangul = part_0_lang == LangCat.HAN
                                continue
                        err_msg = 'Unexpected lang mix={} for \'lang: value\' part={!r} given base'.format(langs, part)
                        raise NameFormatError(err_msg + _parse_dbg(base, cjk, stylized, aka, info, details_parts))
                elif found_hangul and _lang_name.upper() == 'RR' and langs[1] == LangCat.ENG:
                    continue
                elif langs[1] not in LangCat.asian_cats:
                    err_msg = 'Unexpected langs={} for \'lang: value\' part={!r}'.format(langs, part)
                    raise NameFormatError(err_msg + _parse_dbg(base, cjk, stylized, aka, info, details_parts))

                _is_hangul = langs[1] == LangCat.HAN
                if cjk:
                    if _is_hangul and not found_hangul:
                        aka.append(cjk)
                        cjk = alt_lang_val
                        found_hangul = True
                    else:
                        aka.append(alt_lang_val)
                else:
                    cjk = alt_lang_val
                    found_hangul = _is_hangul
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
        elif part.startswith(('pronounced', 'shortened from')):
            pass
        elif lc_part.startswith(('is a ', 'acronym for')) and ((base and cjk) or not details_parts):
            break
        elif found_hangul and lc_part.startswith('rr:'):
            pass
        elif lc_part == 'lit':  # Literal translation of name
            pass
        elif lc_part.startswith('lit. '):
            lit_translation = part[4:].strip()
            if ')' in lit_translation and '(' not in lit_translation:
                lit_translation, remainder = map(str.strip, lit_translation.split(')', 1))
                details_parts.append(remainder)
            aka.append(lit_translation)
        elif year_rx.match(part):
            pass
        else:
            _details_parts = list(map(str.strip, re.split('[;,]', details)))
            _pat = r'{}\s*[;,]\s*{}'.format(regexcape(cjk), regexcape(part)) if cjk else None
            if len(_details_parts) == 2 and cjk and re.match(_pat, details):
                pass    # (cjk; pronunciation of cjk)
            elif lc_part.startswith('born ') and details_parts and details_parts[0][:4].isdigit():
                details_parts.pop(0)
            elif lc_part.startswith('/') and lc_part.endswith('/'):     # IPA pronunciation
                pass
            elif (base and cjk) or base and aka and part.startswith('is a'):
                err_msg = 'Ignoring unexpected part={!r} and returning parsed name early'.format(part)
                log.log(9, err_msg + _parse_dbg(base, cjk, stylized, aka, info, details_parts))
                break
            else:
                err_msg = 'Unexpected part={!r}'.format(part)
                raise NameFormatError(err_msg + _parse_dbg(base, cjk, stylized, aka, info, details_parts))

    return base, cjk, stylized, aka, info


def _parse_dbg(base, cjk, stylized, aka, info, details_parts):
    fmt = ' (base={!r} cjk={!r} stylized={!r} aka={!r} info={!r} remaining={!r})'
    return fmt.format(base, cjk, stylized, aka, info, details_parts)


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
            # elif LangCat.categorize(text) == LangCat.MIX and has_parens(text):
            #     return [split_name(text, True, require_preceder=False)]
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


@cached(LRUCache(100))
def split_name(
    name, unused=False, check_keywords=True, permissive=False, require_preceder=True, allow_cjk_mix=False,
    no_lang_check=False
):
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
    if no_lang_check:
        return parts

    eng, cjk, not_used = None, None, None
    langs = categorize_langs(parts)
    s = 's' if len(parts) > 1 else ''
    log.log(4, 'ParentheticalParser().parse({!r}) => {} part{}: {} ({})'.format(name, len(parts), s, parts, langs))
    if len(parts) == 1:
        part = parts[0]
        lang = langs[0]
        if lang == LangCat.MIX:
            if has_parens(part) and require_preceder:
                return split_name(part, unused, check_keywords, permissive, False, allow_cjk_mix)
            elif ' / ' in part:
                parts = tuple(map(str.strip, part.split(' / ', 1)))
                return split_name(parts, unused, check_keywords, permissive, require_preceder, allow_cjk_mix)
            elif not has_parens(part) and LangCat.matches(part, LangCat.JPN, LangCat.CJK, detailed=True):
                lang = LangCat.JPN
        try:
            eng, cjk = eng_cjk_sort(part, lang)
        except ValueError as e:
            raise ValueError('Unable to split {!r} into separate English/CJK strings'.format(name)) from e
    elif len(parts) == 2:
        if langs == (LangCat.MIX, LangCat.ENG):
            parts = parts[::-1]
            langs = (LangCat.ENG, LangCat.MIX)
        # log.debug('parts={}, langs={}'.format(parts, langs))
        if LangCat.MIX not in langs and len(set(langs)) == 2:
            try:
                eng, cjk = eng_cjk_sort(parts, langs)               # Name (other lang)
            except ValueError as e:
                cjk, not_used = LangCat.sort(parts)
                eng = ''
            else:
                if ' / ' in eng:                                    # Group / Soloist (soloist other lang)
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
        elif langs[0] != LangCat.MIX and langs[1] == LangCat.MIX and has_parens(parts[1]) and not has_parens(parts[0]):
            eng, cjk = eng_cjk_sort(parts[0], langs[0])     # Soloist single lang (Group (group other lang))
            try:
                not_used = split_name(parts[1])
            except Exception:
                not_used = parts[1]
        elif langs == (LangCat.MIX, LangCat.MIX):
            if all(has_parens(p) for p in parts):
                eng, cjk = split_name(parts[0])                 # Soloist (other lang) [Group (group other lang)]
                try:
                    not_used = split_name(parts[1])
                except Exception:
                    not_used = parts[1]
            elif ' X ' in parts[1]:
                if LangCat.categorize(parts[0], True).intersection(LangCat.asian_cats):
                    eng, cjk = '', parts[0]
                else:
                    eng, cjk = parts[0], ''
                not_used = parts[1].split(' X ')
        elif langs == (LangCat.ENG, LangCat.MIX):
            if ' / ' in parts[1]:                           # Soloist (Group / soloist other lang)
                try:
                    not_used, cjk = eng_cjk_sort(parts[1].split(' / '))
                except Exception:
                    pass
                else:
                    eng = parts[0]
            elif ':' in parts[1] and LangCat.categorize(parts[1].split(':', 1)[1]) in LangCat.asian_cats:
                eng = parts[0]                              # eng (lang_name: cjk)
                cjk = parts[1].split(':', 1)[1]
            else:
                common_part_suffix = common_suffix(parts)
                # log.debug('Found common part suffix for {}: {!r}'.format(parts, common_part_suffix))
                if common_part_suffix and LangCat.categorize(parts[1][:-len(common_part_suffix)]) in LangCat.asian_cats:
                    eng, cjk = parts
                else:
                    common_prefix = os.path.commonprefix(parts)
                    if common_prefix and LangCat.categorize(parts[1][len(common_prefix):]) in LangCat.asian_cats:
                        eng, cjk = parts
                    elif '/' in parts[1]:
                        p1_parts = parts[1].split('/', 1)
                        p1_langs = categorize_langs(p1_parts)
                        if len(set(p1_langs)) == 2 and LangCat.ENG not in p1_langs:     # artist lang / hangul
                            try:
                                han_idx = p1_langs.index(LangCat.HAN)
                            except ValueError:
                                pass
                            else:
                                eng = parts[0]
                                cjk = p1_parts[han_idx]
                    elif allow_cjk_mix and LangCat.contains_any_not(parts[1], LangCat.ENG):
                        eng, cjk = parts
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
        elif LangCat.MIX not in langs and len(set(langs)) == 3:     # Soloist (other lang 1) (other lang 2)
            not_used = []
            for part, lang in zip(map(unsurround, parts), langs):
                if lang == LangCat.ENG:
                    eng = part
                elif lang == LangCat.HAN:
                    cjk = part
                else:
                    not_used.append(part)
            if not eng:
                cjk = None
            elif not cjk:
                if len(not_used) == 2:
                    for i, val in enumerate(not_used):
                        if LangCat.categorize(val) in LangCat.asian_cats:
                            cjk = not_used.pop(i)
                            break
                if not cjk:
                    eng = None  # Raise exception
        elif parts[2].upper() == 'OST' and 'OST' not in map(str.upper, parts[:2]):
            eng, cjk = map('{} OST'.format, split_name(tuple(parts[:2])))

    if not eng and not cjk:
        # traceback.print_stack()
        fmt = 'Unable to split {!r} into separate English/CJK strings - parts={}, langs={}'
        raise ValueError(fmt.format(name, parts, langs))

    if check_keywords:
        keywords = ('feat.', 'featuring', 'inst.', 'instrumental')
        lc_eng = eng.lower()
        if lc_eng.startswith(keywords):
            if not cjk and not not_used:
                keyword = next((val for val in keywords if lc_eng.startswith(val)), None)
                if keyword:
                    eng = eng[len(keyword):].strip()
            else:
                log.log(6, 'Shuffling return values due to keywords: {}'.format((eng, cjk, not_used)))
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
        if a in (LangCat.ENG, LangCat.NUL) and (b in LangCat.non_eng_cats or (permissive and b == LangCat.MIX)):
            return strs
        elif a == LangCat.ENG and b == LangCat.NUL:
            return strs
        elif b in (LangCat.ENG, LangCat.NUL) and (a in LangCat.non_eng_cats or (permissive and a == LangCat.MIX)):
            return tuple(reversed(strs))
        elif b == LangCat.ENG and a == LangCat.NUL:
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
