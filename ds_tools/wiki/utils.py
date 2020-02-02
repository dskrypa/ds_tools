"""
:author: Doug Skrypa
"""

import logging
import re

__all__ = ['strip_style']
log = logging.getLogger(__name__)


def strip_style(text, strip=True):
    """
    Strip style tags from the given wiki text string.

    2, 3, or 5 's = italic / bold / italic + bold

    Replaces the need for using mwparserfromhell in addition to wikitextparser.

    :param str text: The text from which style tags should be stripped
    :param bool strip: Also strip leading/trailing spaces
    :return str: The given text, without style tags
    """
    if "''" in text:
        try:
            patterns_a = strip_style._patterns_a
        except AttributeError:
            patterns_a = strip_style._patterns_a = [
                re.compile(r"(''''')(.+?)(\1)"), re.compile(r"(''')(.+?)(\1)"), re.compile(r"('')(.+?)(\1)")
            ]  # Replace longest matches first

        for pat in patterns_a:
            text = pat.sub(r'\2', text)

    try:
        patterns_b = strip_style._patterns_b
    except AttributeError:
        patterns_b = strip_style._patterns_b = [re.compile(r'<(small)>(.+?)</(\1)>')]

    for pat in patterns_b:
        text = pat.sub(r'\2', text)
    return text.strip() if strip else text
