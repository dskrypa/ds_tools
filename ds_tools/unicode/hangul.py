"""
Tools for working with hangul

:author: Doug Skrypa
"""

import re
from itertools import chain, product
from typing import Pattern

from cachetools import LRUCache

from ..caching import cached
from .ranges import HANGUL_RANGES

__all__ = [
    'compose_syllable', 'decompose_syllable', 'decompose_syllables', 'is_final_jamo', 'is_hangul_syllable', 'is_jamo',
    'is_lead_jamo', 'is_vowel_jamo', 'revised_romanize', 'romanize', 'romanize_plus', 'hangul_romanized_permutations',
    'matches_hangul_permutation'
]

# https://en.wikipedia.org/wiki/Hangul_Compatibility_Jamo
JAMO_CONSONANTS_START = 0x3130
JAMO_VOWELS_START = 0x314F
JAMO_VOWELS_END = 0x3163
# The 0x3130 - 0x314E block contains both leading and final consonants - offsets from 0x3130 of lead consonants:
JAMO_LEAD_OFFSETS = [1, 2, 4, 7, 8, 9, 17, 18, 19, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30]
# There are 3 chars that may not be used as a final consonant:
JAMO_END_OFFSETS = [i for i in range(31) if i not in (8, 19, 25)]
SYLLABLES_START, SYLLABLES_END = HANGUL_RANGES[0]
HANGUL_REGEX_CHAR_CLASS = '[{}]'.format(''.join(f'\\u{a:x}-\\u{b:x}' for a, b in HANGUL_RANGES))

# region Romanization Character Constants

ROMANIZED_LEAD_CONSONANTS = [
    'g', 'gg', 'n', 'd', 'dd', 'r', 'm', 'b', 'bb', 's', 'ss', '', 'j', 'jj', 'ch', 'k', 't', 'p', 'h'
]
ROMANIZED_VOWELS = [
    'a', 'ae', 'ya', 'yae', 'eo', 'e', 'yeo', 'ye', 'o', 'wa', 'wae', 'oe', 'yo', 'u', 'weo', 'we', 'wi', 'yu', 'eu',
    'eui', 'i'
]
ROMANIZED_END_CONSONANTS = [
    '', 'g', 'gg', 'gs', 'n', 'nj', 'nh', 'd', 'l', 'rk', 'rm', 'rb', 'rs', 'rt', 'rp', 'rh', 'm', 'b', 'bs', 's', 'ss',
    'ng', 'j', 'ch', 'k', 't', 'p', 'h'
]

LEAD_CONSONANT_PERMUTATIONS = [
    ('k', 'g'), ('kk', 'gg'), 'n', ('t', 'd'), ('tt', 'dd'), ('r', 'l'), 'm', ('p', 'b', 'v'), ('pp', 'bb'), 's', 'ss',
    '', ('ch', 'j'), 'jj', 'ch', 'k', 't', 'p', 'h'
]
VOWEL_PERMUTATIONS = [
    # ㅏ,ㅐ,ㅑ,ㅒ,ㅓ,ㅔ,ㅕ,ㅖ,ㅗ,ㅘ,ㅙ,ㅚ,ㅛ,ㅜ,ㅝ,ㅞ,ㅟ,ㅠ,ㅡ,ㅢ,ㅣ
    'a', 'ae', 'ya', 'yae', ('eo', 'u'), 'e', ('yeo', 'you', 'yu'), 'ye', ('o', 'oh'), 'wa', 'wae', 'oe', 'yo',
    ('u', 'oo'), ('weo', 'wo'), 'we', 'wi', ('yu', 'yoo'), 'eu', ('eui', 'ui', 'ee'), ('i', 'ee', 'y')
]
END_CONSONANT_PERMUTATIONS = [
    # \u3130,ㄱ,ㄲ,ㄳ,ㄴ,ㄵ,ㄶ,ㄷ,ㄹ,ㄺ,ㄻ,
    '', ('k', 'g'), ('kk', 'gg'), ('ks', 'gs'), 'n', 'nj', 'nh', ('d', 't'), ('l', 'r'), ('rk', 'lk'), ('rm', 'lm'),
    # ㄼ,ㄽ,ㄾ,ㄿ,ㅀ,ㅁ,ㅂ,ㅄ,ㅅ,
    ('rb', 'lb'), ('rs', 'ls'), ('rt', 'lt'), ('rp', 'lp'), ('rh', 'lh'), 'm', ('b', 'p'), ('bs', 'ps'), ('s', 't'),
    # ㅆ,ㅇ,ㄿ,ㅀ,ㅁ,ㅂ,ㅄ,ㅅ,ㅆ,ㅇ,ㅈ,ㅊ,ㅋ,ㅌ,ㅍ,ㅎ
    ('ss', 't'), 'ng', ('j', 't'), ('ch', 't'), 'k', 't', 'p', ('h', 't')
]

REVISED_LEAD_CONSONANTS = [
    'g', 'kk', 'n', 'd', 'tt', 'l', 'm', 'b', 'pp', 's', 'ss', '', 'j', 'jj', 'ch', 'k', 't', 'p', 'h'
]
REVISED_VOWELS = [
    'a', 'ae', 'ya', 'yae', 'eo', 'e', 'yeo', 'ye', 'o', 'wa', 'wae', 'oe', 'yo', 'u', 'wo', 'we', 'wi', 'yu', 'eu',
    'ui', 'i'
]
REVISED_END_CONSONANTS = [
    '', 'g', 'kk', 'gs', 'n', 'nj', 'nh', 'd', 'l', 'lg', 'lm', 'lb', 'ls', 'lt', 'lp', 'lh', 'm', 'b', 'bs', 's',
    'ss', 'ng', 'j', 'ch', 'k', 't', 'p', 'h'
]
ROMANIZED_NAME_SYLLABLES = {'희': ('h', 'ee', ''), '이': ('l', 'ee', ''), '박': ('p', 'a', 'rk')}
ROMANIZED_MISC_NAMES = {'죠지': 'george', '일레인': 'elaine'}
SH_VOWELS = {'i', 'yeo', 'ya', 'yo', 'yu'}
T_STOPS = {'s', 'ss', 'j', 'ch', 'h'}
COMBO_CHANGES = {
    'ㄱㄴ': 'ㅇㄴ',
    'ㅋㄴ': 'ㅇㄴ',
    'ㄲㄴ': 'ㅇㄴ',
    'ㄱㅁ': 'ㅇㅁ',
    'ㅋㅁ': 'ㅇㅁ',
    'ㄷㄴ': 'ㄴㄴ',
    'ㄷㅁ': 'ㄴㅁ',
    'ㅅㄴ': 'ㄴㄴ',
    'ㅆㄴ': 'ㄴㄴ',
    'ㅅㅁ': 'ㄴㅁ',
    'ㅈㄴ': 'ㄴㄴ',
    'ㅈㅁ': 'ㄴㅁ',
    'ㅊㄴ': 'ㄴㄴ',
    'ㅊㅁ': 'ㄴㅁ',
    'ㅌㄴ': 'ㄴㄴ',
    'ㅌㅁ': 'ㄴㅁ',
    'ㅎㄴ': 'ㄴㄴ',
    'ㅎㅁ': 'ㄴㅁ',
    'ㅂㄴ': 'ㅁㄴ',
    'ㅂㅁ': 'ㅁㅁ',
    'ㅍㄴ': 'ㅁㄴ',
    'ㅍㅁ': 'ㅁㅁ',
    'ㄱㅎ': 'ㅋㅇ',
    'ㅎㄱ': 'ㅋㅇ',
    'ㅎㄷ': 'ㅌㅇ',
    'ㄷㅎ': 'ㅌㅇ',
    'ㅂㅎ': 'ㅍㅇ',
    'ㅎㅂ': 'ㅍㅇ',
    'ㅈㅎ': 'ㅊㅇ',
    'ㅎㅈ': 'ㅊㅇ',
    'ㅎㅅ': 'ㅆㅇ',
    'ㄱㅅ': 'ㅆㅇ',
    'ㄱㄹ': 'ㅇㄴ',
    'ㄴㄹ': 'ㄹㄹ',
    'ㅁㄹ': 'ㅁㄴ',
    'ㅇㄹ': 'ㅇㄴ',
    'ㅂㄹ': 'ㅁㄴ'
}

# endregion


def ambiguous_romanized() -> set[str]:
    ambiguous = set()
    for final, initial in product(REVISED_END_CONSONANTS, REVISED_LEAD_CONSONANTS):
        first_hit = True
        combined = final + initial
        for i in range(len(combined)):
            if combined[:i] in REVISED_END_CONSONANTS and combined[i:] in REVISED_LEAD_CONSONANTS:
                if first_hit:
                    first_hit = False
                else:
                    ambiguous.add(combined)
                    break
    return ambiguous


AMBIGUOUS_ROMANIZED = ambiguous_romanized()


# region Character Classification

def is_hangul_syllable(char: str) -> bool:
    if len(char) != 1:
        return False
    return SYLLABLES_START <= ord(char) <= SYLLABLES_END


def is_jamo(char: str) -> bool:
    if len(char) != 1:
        return False
    return JAMO_CONSONANTS_START < ord(char) <= JAMO_VOWELS_END


def is_lead_jamo(char: str) -> bool:
    if len(char) != 1:
        return False
    return (ord(char) - JAMO_CONSONANTS_START) in JAMO_LEAD_OFFSETS


def is_vowel_jamo(char: str) -> bool:
    if len(char) != 1:
        return False
    return JAMO_VOWELS_START <= ord(char) <= JAMO_VOWELS_END


def is_final_jamo(char: str) -> bool:
    if len(char) != 1:
        return False
    return (ord(char) - JAMO_CONSONANTS_START) in JAMO_END_OFFSETS

# endregion

# region Decompose / Compose Syllables


def decompose_syllable(syllable: str) -> tuple[str, str, str]:
    """
    Formula from: https://en.wikipedia.org/wiki/Korean_language_and_computers#Hangul_Syllables_block

    :param syllable: A single character that is a hangul syllable
    :return: A 3-tuple of the jamo that composed the original syllable
    """
    # syllable = 588 initial + 28 medial + final + 44032
    i, rem = divmod(ord(syllable) - 44032, 588)
    m, f = divmod(rem, 28)
    jamo = (
        chr(JAMO_CONSONANTS_START + JAMO_LEAD_OFFSETS[i]),
        chr(JAMO_VOWELS_START + m),
        chr(JAMO_CONSONANTS_START + JAMO_END_OFFSETS[f]) if f > 0 else ''
    )
    return jamo


def decomposed_syllable_str(syllable: str) -> str:
    """
    Formula from: https://en.wikipedia.org/wiki/Korean_language_and_computers#Hangul_Syllables_block

    :param syllable: A single character that is a hangul syllable
    :return: A 2-3 character string containing the jamo that composed the original syllable
    """
    # syllable = 588 initial + 28 medial + final + 44032
    i, rem = divmod(ord(syllable) - 44032, 588)
    m, f = divmod(rem, 28)
    a = chr(JAMO_CONSONANTS_START + JAMO_LEAD_OFFSETS[i])
    b = chr(JAMO_VOWELS_START + m)
    c = chr(JAMO_CONSONANTS_START + JAMO_END_OFFSETS[f]) if f > 0 else ''
    return a + b + c


def decompose_syllables(a_str: str) -> str:
    """
    Formula from: https://en.wikipedia.org/wiki/Korean_language_and_computers#Hangul_Syllables_block

    :param a_str: A string
    :return: The provided string with all hangul syllables decomposed to jamo
    """
    if len(a_str) > 1:
        # return ''.join(chain.from_iterable(decompose_syllable(c) for c in a_str))
        return ''.join(map(decomposed_syllable_str, a_str))
    elif not is_hangul_syllable(a_str):                     # This also handles len<1 case
        return a_str
    # return ''.join(decompose_syllable(a_str))
    return decomposed_syllable_str(a_str)


def compose_syllable(lead, vowel, final_consonant='') -> str:
    """
    Composing 2/3 jamo into a single composed syllable is easy; composing a series of jamo into syllables is more
    difficult since some consonants may be used in the first or last position depending on other jamo in the series.

    :param char lead: Lead consonant jamo
    :param char vowel: Vowel jamo
    :param char final_consonant: Final consonant jamo
    :return char: A composed hangul syllable
    """
    initial = JAMO_LEAD_OFFSETS.index(ord(lead) - JAMO_CONSONANTS_START)
    medial = ord(vowel) - JAMO_VOWELS_START
    final = 0 if not final_consonant else JAMO_END_OFFSETS.index(ord(final_consonant) - JAMO_CONSONANTS_START)
    return chr(44032 + (initial * 588) + (medial * 28) + final)

# endregion

# region Romanization


def romanize(text: str, name: bool = False, space: bool = False) -> str:
    romanized = []
    for char in text:
        c_ord = ord(char)
        if SYLLABLES_START <= c_ord <= SYLLABLES_END:
            if name and char in ROMANIZED_NAME_SYLLABLES:
                romanized.extend(ROMANIZED_NAME_SYLLABLES[char])
            else:
                i, rem = divmod(c_ord - 44032, 588)
                m, f = divmod(rem, 28)
                romanized.append(ROMANIZED_LEAD_CONSONANTS[i])
                romanized.append(ROMANIZED_VOWELS[m])
                if f > 0:
                    romanized.append(ROMANIZED_END_CONSONANTS[f])
            if space:
                romanized.append(' ')
        else:
            romanized.append(char)

    return ''.join(romanized).strip()


def revised_romanize(text: str, name: bool = False, space: bool = False) -> str:
    romanized = []
    last_end = None
    for char in text:
        c_ord = ord(char)
        if SYLLABLES_START <= c_ord <= SYLLABLES_END:
            if name and char in ROMANIZED_NAME_SYLLABLES:
                lead, vowel, end = ROMANIZED_NAME_SYLLABLES[char]
                i = None
            else:
                i, rem = divmod(c_ord - 44032, 588)
                m, f = divmod(rem, 28)
                lead = REVISED_LEAD_CONSONANTS[i]
                vowel = REVISED_VOWELS[m]
                end = REVISED_END_CONSONANTS[f] if f > 0 else None

            if romanized and (i == 11 or (last_end and (last_end + lead) in AMBIGUOUS_ROMANIZED)):
                if space and romanized[-1] == ' ':
                    romanized[-1] = '-'
                else:
                    romanized.append('-')

            romanized.append(lead)
            romanized.append(vowel)
            if end:
                romanized.append(end)
            last_end = end
            if space:
                romanized.append(' ')
        else:
            romanized.append(char)
            last_end = None

    return ''.join(romanized).strip()


def romanize_plus(text: str, name: bool = False, space: bool = False) -> str:
    romanized = []
    last_end = None
    last_char = None
    for char in text:
        c_ord = ord(char)
        if SYLLABLES_START <= c_ord <= SYLLABLES_END:
            if name and char in ROMANIZED_NAME_SYLLABLES and ((not romanized or last_char == ' ') or char != '이'):
                lead, vowel, end = ROMANIZED_NAME_SYLLABLES[char]
                i = None
            else:
                i, rem = divmod(c_ord - 44032, 588)
                m, f = divmod(rem, 28)
                lead = REVISED_LEAD_CONSONANTS[i]
                vowel = REVISED_VOWELS[m]
                end = REVISED_END_CONSONANTS[f] if f > 0 else None

            if romanized and last_end and (i == 11 or (last_end + lead) in AMBIGUOUS_ROMANIZED):
                if space and romanized[-1] == ' ':
                    romanized[-1] = '-'
                else:
                    romanized.append('-')

            if lead == 's' and vowel in SH_VOWELS:
                lead = 'sh'
            elif last_end in T_STOPS and i != 11:
                romanized[-2 if space else -1] = 't'

            romanized.append(lead)
            romanized.append(vowel)
            if end:
                romanized.append(end)
            last_end = end
            last_char = end or vowel
            if space:
                romanized.append(' ')
        else:
            romanized.append(char)
            last_char = char
            last_end = None

        if last_end in T_STOPS:
            romanized[-2 if space else -1] = 't'

    return ''.join(romanized).strip()


def _hangul_romanized_permutations(text: str, include_space: bool = False) -> list[str]:
    c_start, end_offsets, lead_offsets = JAMO_CONSONANTS_START, JAMO_END_OFFSETS, JAMO_LEAD_OFFSETS
    romanized = []
    last_char = None
    last_end = None
    for char in text:
        c_ord = ord(char)
        if SYLLABLES_START <= c_ord <= SYLLABLES_END:
            if char in ROMANIZED_NAME_SYLLABLES and ((not romanized or last_char == ' ') or char != '이'):
                lead, vowel, end = ROMANIZED_NAME_SYLLABLES[char]
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

            # doubles = (f'{d[0]}{{1,2}}' if d and d[0] == d[1] else d for d in doubles)
            single_str = '[{}]'.format(''.join(singles)) if singles else None
            double_str = '|'.join(f'{d[0]}{{1,2}}' if d and d[0] == d[1] else d for d in doubles) if doubles else None
            combined = (double_str + '|' + single_str) if single_str and double_str else single_str or double_str
            pat.append('(?:{})'.format(combined) if double_str else combined)  # double always needs the group

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


def hangul_romanized_permutations(text: str, include_space: bool = False) -> list[str]:
    combined_1 = _hangul_romanized_permutations(text, include_space)
    permutations = list(map(str.strip, combo_options(combined_1)))
    if text in ROMANIZED_MISC_NAMES:
        permutations.insert(0, ROMANIZED_MISC_NAMES[text])

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
