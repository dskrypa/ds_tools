"""
Utilities for processing MediaWiki pages into a more usable form.

Notes:\n
  - :mod:`wikitextparser` handles lists, but does not handle stripping of formatting around strings
  - :mod:`mwparserfromhell` does not handle lists, but does handle stripping of formatting around strings
    - Replaced the need for this module for now by implementing :func:`strip_style<.utils.strip_style>`

:author: Doug Skrypa
"""

import logging

from ..compat import cached_property
from .nodes import Root, Template, MixedNode, String

__all__ = ['WikiPage']
log = logging.getLogger(__name__)
IGNORE_CATEGORY_PREFIXES = ('album chart usages for',)


class WikiPage(Root):
    def __init__(self, title, site, content, categories):
        super().__init__(content)
        self.site = site
        self.title = title
        self._categories = categories

    def __repr__(self):
        return f'<{type(self).__name__}[{self.title!r} @ {self.site}]>'

    @cached_property
    def categories(self):
        categories = {cat for cat in map(str.lower, self._categories) if not cat.startswith(IGNORE_CATEGORY_PREFIXES)}
        return categories

    @cached_property
    def infobox(self):
        """
        Turns the infobox into a dict.  Values are returned as :class:`WikiText<wikitextparser.WikiText>` to allow for
        further processing of links or other data structures.  Wiki lists are converted to Python lists of WikiText
        values.
        """
        try:
            for node in self.sections.content:
                if isinstance(node, Template) and 'infobox' in node.name.lower():
                    return node
        except Exception as e:
            log.debug(f'Error iterating over first section content: {e}')
        return None

    @cached_property
    def intro(self):
        """
        Neither parser provides access to the 1st paragraph directly when an infobox template precedes it - need to
        remove the infobox from the 1st section, or any other similar elements.
        """
        try:
            for node in self.sections.content:
                if isinstance(node, (MixedNode, String)):
                    return node
        except Exception as e:
            log.debug(f'Error iterating over first section content: {e}')
        return None