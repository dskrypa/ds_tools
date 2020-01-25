"""
Utilities for processing MediaWiki pages into a more usable form.

Uses two libraries for parsing wikitext due to strengths and limitations of each:\n
  - :mod:`wikitextparser` handles lists, but does not handle stripping of formatting around strings
  - :mod:`mwparserfromhell` does not handle lists, but does handle stripping of formatting around strings

:author: Doug Skrypa
"""

import logging
from collections import OrderedDict

from mwparserfromhell.parser import Parser
from wikitextparser import WikiText

from ..compat import cached_property

__all__ = ['WikiPage', 'WikiPageSection']
log = logging.getLogger(__name__)


class WikiPage:
    def __init__(self, title, site, content, categories):
        self.site = site
        self.title = title
        self.content = content
        self.categories = categories
        self.parsed = WikiText(content)

    def __repr__(self):
        return f'<{type(self).__name__}[{self.title!r} @ {self.site}]>'

    @cached_property
    def infobox(self):
        data = {}
        infobox = self.parsed.templates[0]
        for arg in infobox.arguments:
            key = arg.name.strip()
            list_vals = arg.lists()
            if list_vals:
                vals = []
                for val in map(str.strip, list_vals[0].items):
                    pval = WikiText(val)
                    links = pval.wikilinks
                    if links and links[0].string == val:
                        vals.append(links[0])
                    else:
                        vals.append(pval)
                data[key] = vals
            else:
                data[key] = WikiText(arg.value.strip())
        return data

    @cached_property
    def intro(self):
        infobox_end = self.parsed.templates[0].span[1]
        intro = self.parsed.sections[0][infobox_end:].strip()
        return WikiText(intro)

    @cached_property
    def sections(self):
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
        self.title = Parser().parse(section.title).strip_code().strip()
        self.level = section.level
        self.section = section
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

    def pprint_headers(self, indent=''):
        print(f'{indent}{"=" * self.level}{self.title}{"=" * self.level}')
        for sub_section in self.children.values():
            sub_section.pprint_headers(indent + (' ' * 4))

    def pprint_reprs(self):
        print(f'{" " * (self.level * 4)}{self}')
        for sub_section in self.children.values():
            sub_section.pprint_reprs()
