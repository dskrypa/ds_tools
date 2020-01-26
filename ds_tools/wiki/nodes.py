"""
:author: Doug Skrypa
"""

import logging
import sys
from collections import OrderedDict

from wikitextparser import WikiText

from .utils import strip_style

__all__ = [
    'WikiNode', 'LinkNode', 'ListNode', 'MixedStringNode', 'StringNode', 'TableNode', 'process_table', 'process_list',
    'split_line'
]
log = logging.getLogger(__name__)
PY_LT_37 = sys.version_info.major == 3 and sys.version_info.minor < 7


class WikiNode:
    def __init__(self, value):
        self.value = value

    def __repr__(self):
        return f'<{type(self).__name__}({self.value!r})>'

    @classmethod
    def for_text(cls, text):
        if isinstance(text, str):
            text = WikiText(text)
        return split_line(text)

    def __iter__(self):
        yield from self.value


class StringNode(WikiNode):
    def __str__(self):
        return self.value


class LinkNode(WikiNode):
    def __init__(self, wiki_link):
        self.title = wiki_link.title    # target = title + fragment
        self.text = wiki_link.text
        super().__init__(wiki_link)

    def __repr__(self):
        return f'<{type(self).__name__}({self.value.string!r})>'


class MixedStringNode(WikiNode):
    pass


class ListNode(WikiNode):
    def __init__(self, wiki_list):
        super().__init__(process_list(wiki_list))


class TableNode(WikiNode):
    def __init__(self, table):
        super().__init__(process_table(table))


def process_table(table):
    _dict = OrderedDict if PY_LT_37 else dict               # 3.7+ dict retains insertion order; dict repr is cleaner
    rows = iter(table.cells())
    columns = [strip_style(cell.value) for cell in next(rows)]
    processed = [_dict(zip(columns, map(split_line, row))) for row in rows]
    return processed


def process_list(wiki_list):
    return [split_line(WikiText(val)) for val in map(str.strip, wiki_list.items)]


def split_line(wiki_text):
    """
    Split a line of WikiText into a list of links and strings.  String values will have any style tags stripped.

    :param WikiText wiki_text: A WikiText object representing a single line
    :return WikiNode: A list containing strings and/or WikiLink / WikiText objects
    """
    as_str = strip_style(wiki_text.string)
    links = wiki_text.wikilinks
    if not links:
        return StringNode(as_str)
    elif len(links) == 1 and links[0].string == as_str:
        return LinkNode(links[0])

    content = []
    for link in links:
        before, link_text, as_str = map(str.strip, as_str.partition(link.string))
        if before:
            content.append(before)
        content.append(LinkNode(link))

    if as_str:
        content.append(as_str)
    return MixedStringNode(content)
