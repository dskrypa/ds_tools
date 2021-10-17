"""
:author: Doug Skrypa
"""

import re
from itertools import chain
from typing import Pattern

from cachetools import LRUCache

from ...caching import cached
from .constants import JAMO_START, INITIAL_OFFSETS, FINAL_OFFSETS, SYLLABLES_START, SYLLABLES_END, COMBO_CHANGES
from .constants import ROMANIZED_SHORT_NAMES, ROMANIZED_LONG_NAMES
from .constants import LEAD_CONSONANT_PERMUTATIONS, END_CONSONANT_PERMUTATIONS, VOWEL_PERMUTATIONS

__all__ = ['hangul_romanized_permutations_pattern', 'matches_hangul_permutation', 'hangul_romanized_permutations']

SH_VOWELS = {'i', 'yeo', 'ya', 'yo', 'yu'}
T_STOPS = {'s', 'ss', 'j', 'ch', 'h'}


def _hangul_romanized_permutations(text: str, include_space: bool = False) -> list[str]:
    c_start, end_offsets, lead_offsets = JAMO_START, FINAL_OFFSETS, INITIAL_OFFSETS
    romanized = []
    last_char = None
    last_end = None
    for char in text:
        c_ord = ord(char)
        if SYLLABLES_START <= c_ord <= SYLLABLES_END:
            if char in ROMANIZED_SHORT_NAMES and ((not romanized or last_char == ' ') or char != '이'):
                lead, vowel, end = ROMANIZED_SHORT_NAMES[char]
            else:
                i, rem = divmod(c_ord - 44032, 588)
                m, f = divmod(rem, 28)
                lead = LEAD_CONSONANT_PERMUTATIONS[i]
                # log.debug('{!r} => {}({}) {}({}) {}({})'.format(
                #     char, chr(c_start + lead_offsets[i]), i, chr(m + JAMO_VOWELS_START), m,
                #     chr(c_start + end_offsets[f]) if f > 0 else '-', f
                # ))
                if last_end:
                    _key = chr(c_start + end_offsets[last_end]) + chr(c_start + lead_offsets[i])
                    if _key in COMBO_CHANGES:
                        # log.debug(f'({last_end}, {i})={_key!r} => {COMBO_CHANGES[_key]!r}')
                        a, b = map(ord, COMBO_CHANGES[_key])
                        a = end_offsets.index(a - c_start)
                        b = lead_offsets.index(b - c_start)
                        idx = -2 if romanized[-1] == ' ' else -1
                        old = romanized[idx]
                        addl_end = END_CONSONANT_PERMUTATIONS[a]
                        addl_lead = LEAD_CONSONANT_PERMUTATIONS[b]
                        romanized[idx] = tuple(set(chain(
                            (old,) if isinstance(old, str) else old,
                            (addl_end,) if isinstance(addl_end, str) else addl_end
                        )))
                        # orig_lead = lead
                        lead = tuple(set(chain(
                            (lead,) if isinstance(lead, str) else lead,
                            (addl_lead,) if isinstance(addl_lead, str) else addl_lead
                        )))
                        # log.debug(
                        #     f'{_key!r}({last_end}, {i})=>{COMBO_CHANGES[_key]!r}({a}, {b}) =>>'
                        #     f' {old=} => {romanized[idx]!r}, {orig_lead=} => {lead!r}'
                        # )

                vowel = VOWEL_PERMUTATIONS[m]
                if f > 0:
                    end = END_CONSONANT_PERMUTATIONS[f]
                    last_end = f
                else:
                    end = None
                    last_end = None

                if i == 11:         # ㅇ
                    if m == 8:      # ㅗ
                        vowel = tuple(set((vowel, 'oh') if isinstance(vowel, str) else chain(vowel, ('oh',))))
                    elif m == 13:   # ㅜ
                        lead = tuple(set((lead, 'w') if isinstance(lead, str) else chain(lead, ('w',))))

            if (
                's' in lead
                and (vowel in SH_VOWELS or (isinstance(vowel, tuple) and any(v in SH_VOWELS for v in vowel)))
            ):
                lead = tuple(set((lead, 'sh') if isinstance(lead, str) else chain(lead, ('sh',))))

            romanized.append(lead)
            romanized.append(vowel)
            if end:
                romanized.append(end)
            last_char = end or vowel
            if include_space:
                romanized.append(' ')
        else:
            romanized.append(char)
            last_char = char

    combined_1 = []
    simple = []
    for char in romanized:
        if isinstance(char, tuple):
            if simple:
                combined_1.append(''.join(simple))
                simple = []
            combined_1.append(char)
        else:
            simple.append(char)

    if simple:
        combined_1.append(''.join(simple))

    # log.debug('{!r} => {}'.format(text, combined_1))
    return combined_1


@cached(LRUCache(300))
def hangul_romanized_permutations_pattern(text: str, include_space: bool = False) -> Pattern:
    pat = []
    for chars in _hangul_romanized_permutations(text, include_space):
        if isinstance(chars, str):
            pat.append(chars)
        else:
            singles = []
            doubles = []
            for char in chars:
                if len(char) == 1:
                    singles.append(char)
                else:
                    doubles.append(char)

            single_str = '[{}]'.format(''.join(singles)) if singles else None
            double_str = '|'.join(f'{d[0]}{{1,2}}' if d and d[0] == d[1] else d for d in doubles) if doubles else None
            combined = (double_str + '|' + single_str) if single_str and double_str else single_str or double_str
            pat.append('(?:{})'.format(combined) if double_str else combined)  # double always needs the group

            # TODO: The old code below has a subtle bug where `doubles` is always truthy, so it ends up hiding other
            #  problems, like `우` -> `[w](?:o{1,2}|[u])` instead of letting the `w` be optional
            # doubles = (f'{d[0]}{{1,2}}' if d and d[0] == d[1] else d for d in doubles)
            # if singles and doubles:
            #     single_str = '[{}]'.format(''.join(singles))
            #     double_str = '(?:{}|{})'.format('|'.join(doubles), single_str)
            #     pat.append(double_str)
            # elif singles:
            #     single_str = '[{}]'.format(''.join(singles))
            #     pat.append(single_str)
            # else:
            #     double_str = '(?:{})'.format('|'.join(doubles))
            #     pat.append(double_str)

    return re.compile(''.join(pat), re.IGNORECASE)


def hangul_romanized_permutations(text: str, include_space: bool = False) -> set[str]:
    combined_1 = _hangul_romanized_permutations(text, include_space)
    permutations = set(map(str.strip, combo_options(combined_1)))
    if text in ROMANIZED_LONG_NAMES:
        permutations.add(ROMANIZED_LONG_NAMES[text])

    return permutations


@cached(LRUCache(300))
def matches_hangul_permutation(eng: str, han: str) -> bool:
    lc_letters = set('abcdefghijklmnopqrstuvwxyz')
    lc_eng = ''.join(c for c in eng.lower() if c in lc_letters)
    return bool(hangul_romanized_permutations_pattern(han).match(lc_eng))
    # return lc_eng in {''.join(p.split()) for p in hangul_romanized_permutations(han, False)}

# endregion


def combo_options(list_with_opts, bases=None):
    if bases is None:
        bases = set()

    for i, value in enumerate(list_with_opts):
        if isinstance(value, str):
            if bases:
                bases = {base + value for base in bases}
            else:
                bases.add(value)
        else:
            if bases:
                bases = {base + val for base in bases for val in value}
            else:
                bases = {val for val in value}
            return combo_options(list_with_opts[i+1:], bases)

    return bases
