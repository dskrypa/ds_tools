#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
:author: Doug Skrypa
"""

import collections

from bs4 import BeautifulSoup, DEFAULT_OUTPUT_ENCODING
from bs4.element import AttributeValueWithCharsetSubstitution, EntitySubstitution, NavigableString, Tag, PageElement

__all__ = ["soupify", "fix_html_prettify"]


def soupify(html, mode="html.parser"):
    if not isinstance(html, str):
        try:
            html = html.text
        except AttributeError as e:
            raise TypeError("Only strings or Requests library response objects are supported") from e
    return BeautifulSoup(html, mode)


def fix_html_prettify():
    """
    Monkey-patch key components of BeautifulSoup 4 to cause ``soup.prettify(formatter="html")`` to produce better
    results
    """
    PageElement.decode = decode
    PageElement.decode_contents = decode_contents
    Tag.decode = decode
    Tag.decode_contents = decode_contents


def decode(self, indent_level=None, eventual_encoding=DEFAULT_OUTPUT_ENCODING, formatter="minimal"):
    """Returns a Unicode representation of this tag and its contents.

    :param eventual_encoding: The tag is destined to be encoded into this encoding. This method is _not_ responsible
      for performing that encoding. This information is passed in so that it can be substituted in if the document
      contains a <META> tag that mentions the document's encoding.
    """
    # First off, turn a string formatter into a function. This will stop the lookup from happening over and over again.
    if not isinstance(formatter, collections.Callable):
        formatter = self._formatter_for_name(formatter)

    attrs = []
    if self.attrs:
        for key, val in sorted(self.attrs.items()):
            if val is None:
                decoded = key
            else:
                if isinstance(val, list) or isinstance(val, tuple):
                    val = " ".join(val)
                elif not isinstance(val, str):
                    val = str(val)
                elif isinstance(val, AttributeValueWithCharsetSubstitution) and eventual_encoding is not None:
                    val = val.encode(eventual_encoding)

                text = self.format_string(val, formatter)
                decoded = str(key) + "=" + EntitySubstitution.quoted_attribute_value(text)
            attrs.append(decoded)

    close, closeTag, prefix, space, indent_space = "", "", "", "", ""

    if self.prefix:
        prefix = self.prefix + ":"

    if self.is_empty_element:
        close = "/"
    else:
        closeTag = "</%s%s>" % (prefix, self.name)

    pretty_print = self._should_pretty_print(indent_level)
    has_nested = any(isinstance(c, Tag) for c in self)

    if indent_level is not None:
        indent_space = "    " * (indent_level - 1)

    if pretty_print:
        space = indent_space
        indent_contents = None if not has_nested else indent_level + 1  # Prevent extra newline on deepest nested level
    else:
        indent_contents = None

    contents = self.decode_contents(indent_contents, eventual_encoding, formatter)

    if self.hidden:
        # This is the 'document root' object.
        s = contents
    else:
        s = []
        if indent_level is not None:
            # Even if this particular tag is not pretty-printed, we should indent up to the start of the tag.
            s.append(indent_space)

        attribute_string = ""
        if attrs:
            attribute_string = " " + " ".join(attrs)
        s.append("<%s%s%s%s>" % (prefix, self.name, attribute_string, close))
        if close:
            s.append("\n")

        if has_nested and pretty_print:
            s.append("\n")

        s.append(contents)

        if has_nested and pretty_print:
            if contents and contents[-1] != "\n":
                s.append("\n")
            if closeTag:
                s.append(space)
        s.append(closeTag)

        if indent_level is not None and closeTag and self.next_sibling:
            # Even if this particular tag is not pretty-printed, we're now done with the tag, and we should add a
            # newline if appropriate.
            s.append("\n")
        s = "".join(s)
    return s


def decode_contents(self, indent_level=None, eventual_encoding=DEFAULT_OUTPUT_ENCODING, formatter="minimal"):
    """Renders the contents of this tag as a Unicode string.

    :param indent_level: Each line of the rendering will be indented this many spaces.
    :param eventual_encoding: The tag is destined to be encoded into this encoding. This method is _not_ responsible
      for performing that encoding. This information is passed in so that it can be substituted in if the document
      contains a <META> tag that mentions the document's encoding.
    :param formatter: The output formatter responsible for converting entities to Unicode characters.
    """
    # First off, turn a string formatter into a function. This will stop the lookup from happening over and over again.
    if not isinstance(formatter, collections.Callable):
        formatter = self._formatter_for_name(formatter)

    pretty_print = (indent_level is not None)
    s = []
    for c in self:
        text = None
        if isinstance(c, NavigableString):
            text = c.output_ready(formatter)
        elif isinstance(c, Tag):
            s.append(c.decode(indent_level, eventual_encoding, formatter))
        if text and indent_level and not self.name == "pre":
            text = text.strip()
        if text:
            if pretty_print and not self.name == "pre":
                s.append("    " * (indent_level - 1))
            s.append(text)
            if pretty_print and not self.name == "pre":
                s.append("\n")
    return "".join(s)
