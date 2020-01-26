"""
Utilities for processing MediaWiki pages into a more usable form.

Notes:\n
  - :mod:`wikitextparser` handles lists, but does not handle stripping of formatting around strings
  - :mod:`mwparserfromhell` does not handle lists, but does handle stripping of formatting around strings
    - Replaced the need for this module for now by implementing :func:`strip_style<.utils.strip_style>`

:author: Doug Skrypa
"""

import logging
from collections import OrderedDict

from wikitextparser import WikiText

from ..compat import cached_property
from .nodes import ListNode, WikiNode, TableNode
from .utils import strip_style

__all__ = ['WikiPage', 'WikiPageSection']
log = logging.getLogger(__name__)


class WikiPage:
    def __init__(self, title, site, content, categories):
        self.site = site
        self.title = title
        self.content = content
        self.categories = categories
        self.parsed = WikiText(content.replace('\xa0', ' '))    # \xa0 = non-breaking space / &nbsp;

    def __repr__(self):
        return f'<{type(self).__name__}[{self.title!r} @ {self.site}]>'

    @cached_property
    def infobox(self):
        """
        Turns the infobox into a dict.  Values are returned as :class:`WikiText<wikitextparser.WikiText>` to allow for
        further processing of links or other data structures.  Wiki lists are converted to Python lists of WikiText
        values.
        """
        data = {}
        infobox = self.parsed.templates[0]
        for arg in infobox.arguments:
            key = strip_style(arg.name)
            list_vals = arg.lists()
            if list_vals:
                data[key] = ListNode(list_vals[0])
            else:
                data[key] = WikiNode.for_text(arg.value.strip())
        return data

    @cached_property
    def intro(self):
        """
        Neither parser provides access to the 1st paragraph directly when an infobox template precedes it - need to
        remove the infobox from the 1st section, or any other similar elements.
        """
        intro_section = self.parsed.sections[0]
        templates = intro_section.templates
        if templates:
            infobox_end = templates[0].span[1]
            intro = intro_section[infobox_end:].strip()
            return WikiNode.for_text(intro)

        tags = intro_section.tags()
        if tags:
            tag = tags[0].string
            intro = intro_section.string.partition(tag)[2]
        else:
            intro = intro_section.string

        return WikiNode.for_text(intro)

    @cached_property
    def sections(self):
        """Both parsers provide a flat list of sections - this provides a view of them nested by level"""
        sections = iter(self.parsed.sections)
        root = WikiPageSection(next(sections))
        last_by_level = {0: root}
        for sec in sections:
            parent_lvl = sec.level - 1
            while parent_lvl > 0 and parent_lvl not in last_by_level:
                parent_lvl -= 1
            parent = last_by_level[parent_lvl]
            section = parent.add(sec)
            last_by_level[section.level] = section
        return root


class WikiPageSection:
    """
    A section in a MediaWiki page.  Improves accessibility of nested subsections.  This class should not be instantiated
    directly - it is built by :meth:`WikiPage.sections`.

    Stores the :class:`Section<wikitextparser.Section>` object that contains the real section data.
    """
    def __init__(self, section, parent=None):
        self.title = strip_style(section.title).strip()
        self.level = section.level
        self.raw_content = section
        self.children = OrderedDict()
        self.parent = parent

    def __repr__(self):
        return f'<{type(self).__name__}[{self.level}: {self.title}]>'

    def __getitem__(self, item):
        return self.children[item]

    def add(self, section):
        sub = WikiPageSection(section, self)
        self.children[sub.title] = sub
        return sub

    def find(self, title):
        try:
            return self.children[title]
        except KeyError:
            pass
        for child in self.children.values():
            try:
                return child.find(title)
            except KeyError:
                pass
        raise KeyError(f'Cannot find section={title!r} in {self} or any subsections')

    def content(self):
        """
        WIP - return this section's content, processed into a form that makes it easier to work with
        """
        tables = self.raw_content.tables
        if tables:
            if len(tables) == 1:
                return TableNode(tables[0])
            return [TableNode(t) for t in tables]

        lists = self.raw_content.lists()
        if lists:
            if len(lists) == 1:
                return ListNode(lists[0])
            return [ListNode(lst) for lst in lists]

        return self.raw_content

    def pprint(self, mode='reprs', indent=''):
        if mode == 'content':
            print(self.raw_content.pformat())
            for child in self.children.values():
                child.pprint()
        elif mode == 'headers':
            print(f'{indent}{"=" * self.level}{self.title}{"=" * self.level}')
            for child in self.children.values():
                child.pprint(mode, indent=indent + ' ' * 4)
        elif mode == 'reprs':
            print(f'{indent}{self}')
            for child in self.children.values():
                child.pprint(mode, indent=indent + ' ' * 4)
