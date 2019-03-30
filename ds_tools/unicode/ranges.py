"""
Unicode character ranges

:author: Doug Skrypa
"""

LATIN_RANGES = [        # Source: https://en.wikipedia.org/wiki/List_of_Unicode_characters#Latin_script
    # (0x0000, 0x007F),   # Basic Latin
    # (0x0080, 0x00FF),   # Latin-1 Supplement
    # (0x0100, 0x017F),   # Latin Extended-A
    # (0x0180, 0x024F),   # Latin Extended-B
    (0x0000, 0x024F),   # [Condensed]
    (0x1E00, 0x1EFF),   # Latin Extended Additional
    (0x2C60, 0x2C7F),   # Latin Extended-C
    (0xA720, 0xA7FF),   # Latin Extended-D
    (0xAB30, 0xAB6F),   # Latin Extended-E
]
GREEK_COPTIC_RANGES = [
    (0x0370, 0x03FF),   # Greek and Coptic
    (0x2C80, 0x2CFF),   # Coptic
    (0x102E0, 0x102FF), # Coptic Epact Numbers
    (0x1F00, 0x1FFF),   # Greek Extended
]
CYRILLIC_RANGES = [     # Source: https://en.wikipedia.org/wiki/Cyrillic_script_in_Unicode
    # (0x0400, 0x04FF),   # Cyrillic
    # (0x0500, 0x052F),   # Cyrillic Supplement
    (0x0400, 0x052F),   # [Condensed]
    (0x2DE0, 0x2DFF),   # Cyrillic Extended-A
    (0xA640, 0xA69F),   # Cyrillic Extended-B
    (0x1C80, 0x1C8F),   # Cyrillic Extended-C
    (0x1D2B, 0x1D78),   # Phonetic Extensions
    (0xFE2E, 0xFE2F),   # Combining Half Marks
]
HANGUL_RANGES = [       # Source: https://en.wikipedia.org/wiki/Korean_language_and_computers#Hangul_in_Unicode
    (0xAC00, 0xD7A3),   # Hangul syllables
    (0x1100, 0x11FF),   # Hangul Jamo
    (0x3130, 0x318F),   # Hangul Compatibility Jamo
    (0xA960, 0xA97F),   # Hangul Jamo Extended-A
    (0xD7B0, 0xD7FF),   # Hangul Jamo Extended-B
    (0xFFA0, 0xFFDC),   # Halfwidth and Fullwidth Forms (Hangul)
]
CJK_RANGES = [          # Source: https://en.wikipedia.org/wiki/CJK_Unified_Ideographs
    (0x4E00, 0x9FFF),   # CJK Unified Ideographs
    (0x3400, 0x4DBF),   # CJK Unified Ideographs Extension A
    (0x20000, 0x2A6DF), # CJK Unified Ideographs Extension B
    # (0x2A700, 0x2B73F), # CJK Unified Ideographs Extension C
    # (0x2B740, 0x2B81F), # CJK Unified Ideographs Extension D
    # (0x2B820, 0x2CEAF), # CJK Unified Ideographs Extension E
    # (0x2CEB0, 0x2EBEF), # CJK Unified Ideographs Extension F
    (0x2A700, 0x2EBEF), # [Condensed]
    # (0x2E80, 0x2EFF),   # CJK Radicals Supplement
    # (0x2F00, 0x2FDF),   # Kangxi Radicals
    # (0x2FF0, 0x2FFF),   # Ideographic Description Characters
    # (0x3000, 0x303F),   # CJK Symbols and Punctuation
    (0x2E80, 0x303F),   # [Condensed]
    (0x31C0, 0x31EF),   # CJK Strokes
    # (0x3200, 0x32FF),   # Enclosed CJK Letters and Months
    # (0x3300, 0x33FF),   # CJK Compatibility
    (0x3200, 0x33FF),   # [Condensed]
    (0xF900, 0xFAFF),   # CJK Compatibility Ideographs
    (0xFE30, 0xFE4F),   # CJK Compatibility Forms
    (0x1F200, 0x1F2FF), # Enclosed Ideographic Supplement
    (0x2F800, 0x2FA1F), # CJK Compatibility Ideographs Supplement
]
KATAKANA_RANGES = [     # Source: https://en.wikipedia.org/wiki/Katakana#Unicode
    (0x30A0, 0x30FF),   # Katakana
    (0xFF65, 0xFF9F),   # Halfwidth and Fullwidth Forms (Katakana)
    (0x32D0, 0x32FE),   # Enclosed CJK Letters and Months (Katakana)
    (0x31F0, 0x31FF),   # Katakana Phonetic Extensions
    (0x1B000, 0x1B0FF), # Kana Supplement
    # (0x3099, 0x3099),   # COMBINING KATAKANA-HIRAGANA VOICED SOUND MARK (non-spacing dakuten)
    # (0x309A, 0x309C),   # (sound marks)
    (0x3099, 0x309C),   # [Condensed]
    (0x1F201, 0x1F202), # SQUARED KATAKANA KOKO, SA
    (0x1F213, 0x1F213), # SQUARED KATAKANA DE
]
HIRAGANA_RANGES = [     # Source: https://en.wikipedia.org/wiki/Hiragana#Unicode
    (0x3040, 0x309F),   # Hiragana
    (0x1B100, 0x1B120), # Kana Extended-A
]
# The following are not technically considered CJK, but will be for the purposes of this library
THAI_RANGES = [         # Source: https://en.wikipedia.org/wiki/Thai_alphabet#Unicode
    (0x0E00, 0x0E7F)    # Thai
]
JAPANESE_RANGES = KATAKANA_RANGES + HIRAGANA_RANGES
NON_ENG_RANGES = HANGUL_RANGES + JAPANESE_RANGES + CJK_RANGES + THAI_RANGES
