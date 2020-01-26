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
from .nodes import Root, as_node, MappingNode
from .utils import strip_style

__all__ = ['WikiPage']
log = logging.getLogger(__name__)


class WikiPage(Root):
    def __init__(self, title, site, content, categories):
        super().__init__(content)
        self.site = site
        self.title = title
        self.categories = categories

    def __repr__(self):
        return f'<{type(self).__name__}[{self.title!r} @ {self.site}]>'

    @cached_property
    def infobox(self):
        """
        Turns the infobox into a dict.  Values are returned as :class:`WikiText<wikitextparser.WikiText>` to allow for
        further processing of links or other data structures.  Wiki lists are converted to Python lists of WikiText
        values.
        """
        templates = self.raw.sections[0].templates
        if templates:
            infobox = templates[0]
            node = MappingNode(infobox)
            for arg in infobox.arguments:
                key = strip_style(arg.name)
                node[key] = as_node(arg.value.strip())
            return node
        return None

    @cached_property
    def intro(self):
        """
        Neither parser provides access to the 1st paragraph directly when an infobox template precedes it - need to
        remove the infobox from the 1st section, or any other similar elements.
        """
        intro_section = self.raw.sections[0]
        templates = intro_section.templates
        if templates:
            infobox_end = templates[0].span[1]
            intro = intro_section[infobox_end:].strip()
            return as_node(intro)

        tags = intro_section.tags()
        if tags:
            tag = tags[0].string
            intro = intro_section.string.partition(tag)[2]
        else:
            intro = intro_section.string
        return as_node(intro)
