from ..ranges import HANGUL_RANGES

# https://en.wikipedia.org/wiki/Hangul_Compatibility_Jamo
JAMO_START = 0x3130
MEDIAL_START = 0x314F
MEDIAL_END = 0x3163
# The 0x3130 - 0x314E block contains both leading and final consonants - offsets from 0x3130 of lead consonants:
INITIAL_OFFSETS = [1, 2, 4, 7, 8, 9, 17, 18, 19, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30]
# There are 3 chars that may not be used as a final consonant:
FINAL_OFFSETS = [i for i in range(31) if i not in (8, 19, 25)]

SYLLABLES_START, SYLLABLES_END = HANGUL_RANGES[0]
HANGUL_REGEX_CHAR_CLASS = '[{}]'.format(''.join(f'\\u{a:x}-\\u{b:x}' for a, b in HANGUL_RANGES))

ROMANIZED_SHORT_NAMES = {'희': 'hee', '이': 'lee', '박': 'park'}
ROMANIZED_LONG_NAMES = {'죠지': 'george', '일레인': 'elaine'}

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
    'ㄹㄴ': 'ㄹㄹ',
    'ㅁㄹ': 'ㅁㄴ',
    'ㅇㄹ': 'ㅇㄴ',
    'ㅂㄹ': 'ㅁㄴ',
}

# region Old Romanization Character Constants

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

# endregion

