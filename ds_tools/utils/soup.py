"""
Utilities for working with HTML / BeautifulSoup

Notes:
    - The 'text' attribute contains text from all child elements of a given element, stripped of any HTML tags
    - The 'string' attribute contains text from only the given element
    - If an element does not directly contain text, its 'text' attribute may have a value, but its 'string' attribute
      will be None
    - It is possible to set the value of an element's 'string' attribute, but not its 'text' attribute
    - The 'strings' attribute is a generator that yields each child element's 'string' value
        - The 'stripped_strings' attr does the same, but stripping each of extra whitespace before yielding them
    - Using element.attr notation for undefined attributes will return the result of element.find(attr)
    - Calling an element (i.e., element(args, kwargs)) is equivalent to calling element.find_all(args, kwargs)


BeatifulSoup element attributes:
# Search for elements
find / find_all
find_next / find_all_next / find_next_sibling / find_next_siblings
find_previous / find_all_previous / find_previous_sibling / find_previous_siblings
find_parent / find_parents
index       # Find the index of a child of this element by identity, not value

# Search for elements using CSS selection notation:
select / select_one

# Element basic info
name        # Tag name/type (i.e., 'a', 'div', 'h1', etc.)
prefix      # Tag name prefix
contents    # Strings or other elements that this element contains

# Element attribute inspection
attrs
get
has_attr

# Text / string extraction
get_text / text
string
strings / stripped_strings

# Methods to alter the HTML by inserting a given element
append / insert
insert_after / insert_before
replace_with / replace_with_children

# Walk through elements
children / descendants
next / previous
next_element / previous_element
next_elements / previous_elements
next_sibling / previous_sibling
next_siblings / previous_siblings
parent / parents

# Render element + contents as str / bytes
decode / encode
decode_contents / encode_contents
prettify

# Other
can_be_empty_element    # Bool - whether this element can be self-closing (like <br/>)
is_empty_element        # Bool - self-closing (like <br/>)
clear                   # Extract / decompose all children
decompose               # Destroy the contents of this element
extract                 # Destructively removes this element from the tree; like pop
format_string
hidden
namespace
parser_class
preserve_whitespace_tags
quoted_colon
setup
wrap / unwrap


:author: Doug Skrypa
"""

import logging
import re
from collections import Callable, OrderedDict
from collections.abc import Iterable, Container
from urllib.parse import urlparse

try:
    # noinspection PyUnresolvedReferences
    from bs4 import BeautifulSoup, DEFAULT_OUTPUT_ENCODING
    # noinspection PyUnresolvedReferences
    from bs4.element import AttributeValueWithCharsetSubstitution, NavigableString, Tag, PageElement
except ImportError:
    bs4_available = False
else:
    try:
        from bs4.dammit import EntitySubstitution       # Location in 4.8.2
    except ImportError:
        # noinspection PyUnresolvedReferences
        from bs4.element import EntitySubstitution      # Location in 4.7.1
    bs4_available = True

__all__ = ['soupify', 'fix_html_prettify', 'HtmlSoup']

log = logging.getLogger(__name__)

_regex_pattern_type = type(re.compile(''))


def soupify(html, mode='lxml', *args, **kwargs):
    if not isinstance(html, str):
        try:
            html = html.text
        except AttributeError as e:
            raise TypeError('Only strings or Requests library response objects are supported') from e
    return BeautifulSoup(html, mode, *args, **kwargs)


def fix_html_prettify():
    """
    Monkey-patch key components of BeautifulSoup 4 to cause ``soup.prettify(formatter='html')`` to produce better
    results
    """
    PageElement.decode = decode
    PageElement.decode_contents = decode_contents
    Tag.decode = decode
    Tag.decode_contents = decode_contents


def _should_skip(content, match_value):
    if (match_value and not content) or (content and not match_value):
        return True
    elif isinstance(match_value, str) and (content != match_value):
        return True
    elif isinstance(match_value, _regex_pattern_type) and not match_value.match(content):
        return True
    elif isinstance(match_value, (Iterable, Container)) and (content not in match_value):
        return True
    elif isinstance(match_value, Callable) and not match_value(content):
        return True
    return False


class HtmlSoup:
    def __init__(self, content, mode='html.parser'):
        if not isinstance(content, (BeautifulSoup, str)) and hasattr(content, 'text'):  # requests.Response
            content = content.text
        if isinstance(content, str):
            content = BeautifulSoup(content, mode)
        if not isinstance(content, BeautifulSoup):
            raise TypeError('Unexpected HTML content type: {}'.format(type(content).__name__))

        self.soup = content

    def links(self, href=None, scheme=None, host=None, path=None, query=None, fragment=None, text=None):
        """
        Generator that yields bs4.element.Tag objects from this HtmlSoup, optionally with the provided filters.

        All filter values may be provided as a bool / str / compiled regex pattern / iterable / container / callable.
        """
        filters = OrderedDict((
            ('scheme', scheme), ('hostname', host), ('path', path), ('query', query), ('fragment', fragment)
        ))

        for a in self.soup.find_all('a'):
            a_href = a.get('href')
            if (href is not None) and _should_skip(a_href, href):
                continue
            elif any(val is not None for val in filters.values()):
                try:
                    url = urlparse(a_href)
                except Exception as e:
                    log.error('Unable to parse URL from href in anchor: {}'.format(a))
                    continue

                skip = False
                for attr, with_val in filters.items():
                    if (with_val is not None) and _should_skip(getattr(url, attr), with_val):
                        skip = True
                        break
                if skip:
                    continue
            elif (text is not None) and _should_skip(a.text, text):
                continue

            yield a

    def hrefs(self, *args, **kwargs):
        for a in self.links(*args, **kwargs):
            yield a['href']

    def urls(self, *args, **kwargs):
        for a in self.links(*args, **kwargs):
            yield urlparse(a['href'])


# Monkey patches for formatting BeautifulSoup objects back into HTML follow ============================================


def decode(self, indent_level=None, eventual_encoding=DEFAULT_OUTPUT_ENCODING, formatter='minimal'):
    """Returns a Unicode representation of this tag and its contents.

    :param eventual_encoding: The tag is destined to be encoded into this encoding. This method is _not_ responsible
      for performing that encoding. This information is passed in so that it can be substituted in if the document
      contains a <META> tag that mentions the document's encoding.
    """
    # First off, turn a string formatter into a function. This will stop the lookup from happening over and over again.
    if not isinstance(formatter, Callable):
        formatter = self._formatter_for_name(formatter)

    attrs = []
    if self.attrs:
        for key, val in sorted(self.attrs.items()):
            if val is None:
                decoded = key
            else:
                if isinstance(val, list) or isinstance(val, tuple):
                    val = ' '.join(val)
                elif not isinstance(val, str):
                    val = str(val)
                elif isinstance(val, AttributeValueWithCharsetSubstitution) and eventual_encoding is not None:
                    val = val.encode(eventual_encoding)

                text = self.format_string(val, formatter)
                decoded = str(key) + '=' + EntitySubstitution.quoted_attribute_value(text)
            attrs.append(decoded)

    close, closeTag, prefix, space, indent_space = '', '', '', '', ''

    if self.prefix:
        prefix = self.prefix + ':'

    if self.is_empty_element:
        close = '/'
    else:
        closeTag = '</%s%s>' % (prefix, self.name)

    pretty_print = self._should_pretty_print(indent_level)
    has_nested = any(isinstance(c, Tag) for c in self)

    if indent_level is not None:
        indent_space = '    ' * (indent_level - 1)

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

        attribute_string = ''
        if attrs:
            attribute_string = ' ' + ' '.join(attrs)
        s.append('<%s%s%s%s>' % (prefix, self.name, attribute_string, close))
        if close:
            s.append('\n')

        if has_nested and pretty_print:
            s.append('\n')

        s.append(contents)

        if has_nested and pretty_print:
            if contents and contents[-1] != '\n':
                s.append('\n')
            if closeTag:
                s.append(space)
        s.append(closeTag)

        if indent_level is not None and closeTag and self.next_sibling:
            # Even if this particular tag is not pretty-printed, we're now done with the tag, and we should add a
            # newline if appropriate.
            s.append('\n')
        s = ''.join(s)
    return s


def decode_contents(self, indent_level=None, eventual_encoding=DEFAULT_OUTPUT_ENCODING, formatter='minimal'):
    """Renders the contents of this tag as a Unicode string.

    :param indent_level: Each line of the rendering will be indented this many spaces.
    :param eventual_encoding: The tag is destined to be encoded into this encoding. This method is _not_ responsible
      for performing that encoding. This information is passed in so that it can be substituted in if the document
      contains a <META> tag that mentions the document's encoding.
    :param formatter: The output formatter responsible for converting entities to Unicode characters.
    """
    # First off, turn a string formatter into a function. This will stop the lookup from happening over and over again.
    if not isinstance(formatter, Callable):
        formatter = self._formatter_for_name(formatter)

    pretty_print = (indent_level is not None)
    s = []
    for c in self:
        text = None
        if isinstance(c, NavigableString):
            text = c.output_ready(formatter)
        elif isinstance(c, Tag):
            s.append(c.decode(indent_level, eventual_encoding, formatter))
        if text and indent_level and not self.name == 'pre':
            text = text.strip()
        if text:
            if pretty_print and not self.name == 'pre':
                s.append('    ' * (indent_level - 1))
            s.append(text)
            if pretty_print and not self.name == 'pre':
                s.append('\n')
    return ''.join(s)


# If BS4 is unavailable, make functions raise RuntimeErrors

if not bs4_available:
    def _missing_dependency(*args, **kwargs):
        raise RuntimeError('Please install beautifulsoup4 to use this function')

    soupify = _missing_dependency
    fix_html_prettify = _missing_dependency
    HtmlSoup.__init__ = _missing_dependency
