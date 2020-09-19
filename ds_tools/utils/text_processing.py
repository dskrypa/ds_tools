"""
Text processing utilities.

:author: Doug Skrypa
"""

from os.path import commonprefix

__all__ = [
    'strip_punctuation', 'unsurround', 'normalize_roman_numerals', 'common_suffix', 'has_unpaired', 'regexcape',
    'has_nested'
]


def chars_by_category(cat=None, prefix=None):
    # ALL_NUMS = ''.join(re.findall(r'\d', ''.join(chr(c) for c in range(sys.maxunicode + 1))))
    # Note: ALL_WHITESPACE is a superset of chars_by_category('Zs')
    try:
        chars = chars_by_category._chars
    except AttributeError:
        import sys
        from collections import defaultdict
        from unicodedata import category
        chars_by_cat = defaultdict(list)
        for c in map(chr, range(sys.maxunicode + 1)):
            chars_by_cat[category(c)].append(c)
        chars = chars_by_category._chars = {cat: ''.join(chars) for cat, chars in chars_by_cat.items()}

    if cat:
        return chars[cat]
    elif prefix:
        from itertools import chain
        return ''.join(chain.from_iterable(chrs for cat, chrs in chars.items() if cat.startswith(prefix)))
    else:
        return chars


def regexcape(text):
    try:
        table = regexcape._table
    except AttributeError:
        table = regexcape._table = str.maketrans({c: '\\' + c for c in '()[]{}^$+*.?|\\'})
    return text.translate(table)


def has_unpaired(text, opener='(', closer=')'):
    opened = 0
    closed = 0
    for c in text:
        if c == opener:
            opened += 1
        elif c == closer:
            closed += 1
            if closed > opened:
                return True
    return opened != closed


def has_nested(text, opener='(', closer=')'):
    opened = 0
    closed = 0
    for c in text:
        if c == opener:
            opened += 1
            if opened - closed > 1:
                return True
        elif c == closer:
            closed += 1
    return False


def common_suffix(strs):
    return ''.join(reversed(commonprefix(list(map(lambda x: ''.join(reversed(x)), strs)))))


def normalize_roman_numerals(text):
    """
    Normalizes Roman Numerals of unicode category `Nl <https://www.compart.com/en/unicode/category/Nl>`_ using
    unicode normalization form NFKC.

    :param str text: A string
    :return str: The string, with Roman Numerals replaced with easier to use equivalents
    """
    from unicodedata import normalize
    return ''.join(normalize('NFKC', c) if 0x2160 <= ord(c) <= 0x217B else c for c in text)


def unsurround(a_str, *chars):
    a_str = a_str.strip()
    chars = chars or (('"', '"'), ('(', ')'), ('“', '“'), ("'", "'"))
    for a, b in chars:
        if a_str.startswith(a) and a_str.endswith(b):
            a_str = a_str[1:-1].strip()
    return a_str


def strip_punctuation(a_str):
    try:
        sub = strip_punctuation._sub
        table = strip_punctuation._table
    except AttributeError:
        import re
        import string
        sub = strip_punctuation._sub = re.compile(r'\s+').sub
        table = strip_punctuation._table = str.maketrans({c: '' for c in string.punctuation})
    return sub('', a_str).translate(table)
