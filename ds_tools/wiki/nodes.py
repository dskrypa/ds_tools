"""
Takes the next step with WikiText parsed by :mod:`wikitextparser` to process it into nodes based on what each section
actually contains.  This is only necessary because that library stops short of providing a fully processed tree; it
returns a generic :class:`WikiText<wikitextparser.WikiText>` object that must be poked and prodded to extract nested
data structures.

This is still a work in process - some data types are not fully handled yet, and some aspects are subject to change.

:author: Doug Skrypa
"""

import logging
import re
import sys
from collections import OrderedDict
from collections.abc import MutableMapping

from wikitextparser import WikiText

from ..compat import cached_property
# from ..output import colored
from .utils import strip_style

__all__ = [
    'Node', 'BasicNode', 'CompoundNode', 'MappingNode', 'MixedNode', 'String', 'Link', 'List', 'Table', 'Template',
    'Root', 'Section', 'as_node', 'extract_links', 'TableSeparator'
]
log = logging.getLogger(__name__)
PY_LT_37 = sys.version_info.major == 3 and sys.version_info.minor < 7
ordered_dict = OrderedDict if PY_LT_37 else dict            # 3.7+ dict retains insertion order; dict repr is cleaner
_NotSet = object()


class Node:
    def __init__(self, raw, root=None, preserve_comments=False):
        if isinstance(raw, str):
            raw = WikiText(raw)
        self.raw = raw
        self.preserve_comments = preserve_comments
        self.root = root

    def stripped(self, *args, **kwargs):
        return strip_style(self.raw.string, *args, **kwargs)

    def __repr__(self):
        return f'<{type(self).__name__}()>'

    def pprint(self):
        print(self.raw.pformat())


class BasicNode(Node):
    def __repr__(self):
        return f'<{type(self).__name__}({self.raw!r})>'


class CompoundNode(Node):
    @cached_property
    def children(self):
        return []

    def __repr__(self):
        return f'<{type(self).__name__}({self.children!r})>'

    def __getitem__(self, item):
        return self.children[item]

    def __setitem__(self, key, value):
        self.children[key] = value

    def __delitem__(self, key):
        del self.children[key]

    def __iter__(self):
        return iter(self.children)

    def __len__(self):
        return len(self.children)

    def find_all(self, node_cls, recurse=False, **kwargs):
        """
        Find all descendent nodes of the given type, optionally with additional matching criteria.

        :param type node_cls: The class of :class:`Node` to find
        :param bool recurse: Whether descendent nodes should be searched recursively or just the direct children of this
          node
        :param kwargs: If specified, keys should be names of attributes of the discovered nodes, for which the value of
          the node's attribute must equal the provided value
        :return: Generator that yields :class:`Node` objects of the given type
        """
        for value in self:
            if isinstance(value, node_cls):
                if not kwargs or all(getattr(value, k, _NotSet) == v for k, v in kwargs.items()):
                    yield value
            if recurse and isinstance(value, CompoundNode):
                yield from value.find_all(node_cls, recurse, **kwargs)

    def find_one(self, *args, **kwargs):
        """
        :param args: Positional args to pass to :meth:`.find_all`
        :param kwargs: Keyword args to pass to :meth:`.find_all`
        :return: The first :class:`Node` object that matches the given criteria, or None if no matching nodes could be
          found.
        """
        return next(self.find_all(*args, **kwargs), None)


class MappingNode(CompoundNode, MutableMapping):
    def __init__(self, raw, root=None, preserve_comments=False, content=None):
        super().__init__(raw, root, preserve_comments)
        if content:
            self.children.update(content)

    @cached_property
    def children(self):
        return ordered_dict()


class MixedNode(CompoundNode):
    """A node that contains text and links"""
    @cached_property
    def children(self):
        return extract_links(self.raw, self.root)


class String(BasicNode):
    def __init__(self, raw, root=None):
        super().__init__(raw, root)
        self.value = strip_style(self.raw.string)

    def __repr__(self):
        return f'<{type(self).__name__}({self.raw.string.strip()!r})>'

    def __str__(self):
        return self.value


class Link(BasicNode):
    def __init__(self, raw, root=None):
        super().__init__(raw, root)
        self.link = self.raw.wikilinks[0]
        self.title = self.link.title    # target = title + fragment
        self.text = self.link.text

    @cached_property
    def interwiki(self):
        return ':' in self.title

    @cached_property
    def iw_key_title(self):
        if self.interwiki:
            iw_site, iw_title = map(str.strip, self.title.split(':', maxsplit=1))
            return iw_site.lower(), iw_title
        raise ValueError(f'{self} is not an interwiki link')

    def __repr__(self):
        if self.root and self.root.site:
            return f'<{type(self).__name__}({self.link.string!r}) @ {self.root.site}>'
        return f'<{type(self).__name__}({self.link.string!r})>'


class ListEntry(CompoundNode):
    def __init__(self, raw, root=None, preserve_comments=False):
        super().__init__(raw, root, preserve_comments)
        if type(self.raw) is WikiText:
            try:
                as_list = self.raw.lists()[0]
            except IndexError:
                self.value = as_node(self.raw, self.root, preserve_comments)
                self._children = None
            else:
                self.value = as_node(as_list.items[0], self.root, preserve_comments)
                try:
                    self._children = as_list.sublists()[0].string
                except IndexError:
                    self._children = None

    def __repr__(self):
        if self._children:
            return f'<{type(self).__name__}({self.value!r}, {self.children!r})>'
        return f'<{type(self).__name__}({self.value!r})>'

    @cached_property
    def sub_list(self):
        if not self._children:
            return None
        content = '\n'.join(c[1:] for c in map(str.strip, self._children.splitlines()))
        return List(content, self.root, self.preserve_comments)

    @cached_property
    def children(self):
        sub_list = self.sub_list
        if not sub_list:
            return []
        return sub_list.children


class List(CompoundNode):
    def __init__(self, raw, root=None, preserve_comments=False):
        super().__init__(raw, root, preserve_comments)
        if type(self.raw) is WikiText:
            try:
                self.raw = self.raw.lists()[0]
            except IndexError as e:
                raise ValueError('Invalid wiki list value') from e

    @cached_property
    def children(self):
        return [ListEntry(val, self.root, self.preserve_comments) for val in map(str.strip, self.raw.fullitems)]

    def iter_flat(self):
        for child in self.children:
            yield child.value
            if child.sub_list:
                yield from child.sub_list.iter_flat()

    def as_dict(self, sep=':'):
        data = {}
        node_fn = lambda x: as_node(x.strip(), self.root, self.preserve_comments)
        for line in map(str.strip, self.raw.items):
            key, val = map(node_fn, line.split(sep, maxsplit=1))
            if isinstance(key, String):
                data[key.value] = val
            elif isinstance(key, Link):
                data[key.text] = val
            else:
                data[key.raw.string] = val
                log.debug(f'Unexpected key type on line: {line!r}')
        return data


class Table(CompoundNode):
    _rowspan_with_template = re.compile(r'(\|\s*rowspan="\d+")\s*{')

    def __init__(self, raw, root=None, preserve_comments=False):
        raw = self._rowspan_with_template.sub(r'\1 | {', raw.string if isinstance(raw, WikiText) else raw)
        super().__init__(raw, root, preserve_comments)
        if type(self.raw) is WikiText:
            try:
                self.raw = self.raw.tables[0]
            except IndexError as e:
                raise ValueError('Invalid wiki table value') from e
        self.caption = self.raw.caption.strip() if self.raw.caption else None
        self._header_rows = None
        self._raw_headers = None

    @cached_property
    def headers(self):
        rows = self.raw.cells()
        row_spans = [int(cell.attrs.get('rowspan', 1)) if cell is not None else 1 for cell in next(iter(rows))]
        self._header_rows = max(row_spans)
        self._raw_headers = []
        str_headers = []

        for i, row in enumerate(rows):
            if i == self._header_rows:
                break
            row_data = [as_node(cell.value.strip(), self.root, self.preserve_comments) for cell in row]
            self._raw_headers.append(row_data)
            cell_strs = []
            for cell in row_data:
                while isinstance(cell, CompoundNode):
                    cell = cell[0]
                if isinstance(cell, String):
                    cell_strs.append(cell.value)
                elif isinstance(cell, Link):
                    cell_strs.append(cell.text)
                elif cell is not None:
                    log.debug(f'Unexpected cell type; using data instead: {cell}')
            str_headers.append(cell_strs)

        headers = []
        for row_span, *header_vals in zip(row_spans, *str_headers):
            header_vals = header_vals[:-(row_span - 1)] if row_span > 1 else header_vals
            headers.append(':'.join(map(strip_style, filter(None, header_vals))))
        return headers

    @cached_property
    def children(self):
        headers = self.headers
        node_fn = lambda cell: as_node(cell.value.strip(), self.root, self.preserve_comments)
        processed = []
        for row in self.raw.cells()[self._header_rows:]:
            if int(row[0].attrs.get('colspan', 1)) >= len(headers):  # Some tables have an incorrect value...
                processed.append(TableSeparator(node_fn(row[0])))
            else:
                mapping = zip(headers, map(node_fn, row))
                processed.append(MappingNode(row, self.root, self.preserve_comments, mapping))
        return processed


class TableSeparator:
    def __init__(self, value):
        self.value = value

    def __repr__(self):
        return f'<{type(self).__name__}({self.value!r})>'


class Template(BasicNode):
    def __init__(self, raw, root=None, preserve_comments=False):
        super().__init__(raw, root, preserve_comments)
        self.name = self.raw.name.strip()

    def __repr__(self):
        return f'<{type(self).__name__}({self.name!r}: {self.value!r})>'

    @cached_property
    def value(self):
        args = self.raw.arguments
        if not args:
            return None
        arg = args[0]
        if arg.name == '1' and arg.string.startswith('|'):
            if len(args) == 1:
                return as_node(arg.value, self.root, self.preserve_comments)
            return [as_node(a.value, self.root, self.preserve_comments) for a in args]
        elif self.name.lower() == 'n/a':
            return arg.value or 'N/A'

        mapping = MappingNode(self.raw, self.root, self.preserve_comments)
        for arg in args:
            key = strip_style(arg.name)
            mapping[key] = as_node(arg.value.strip(), self.root, self.preserve_comments, strict_tags=True)
        return mapping

    def __getitem__(self, item):
        if self.value is None:
            raise TypeError('Cannot index a template with no value')
        return self.value[item]


class Root(Node):
    # Children = sections
    def __init__(self, page_text, site=None, preserve_comments=False):
        if isinstance(page_text, str):
            page_text = WikiText(page_text.replace('\xa0', ' '))
        super().__init__(page_text, None, preserve_comments)
        self.site = site

    def __getitem__(self, item):
        return self.sections[item]

    @cached_property
    def sections(self):
        sections = iter(self.raw.sections)
        root = Section(next(sections), self, self.preserve_comments)
        last_by_level = {0: root}
        for sec in sections:
            parent_lvl = sec.level - 1
            while parent_lvl > 0 and parent_lvl not in last_by_level:
                parent_lvl -= 1
            parent = last_by_level[parent_lvl]
            section = Section(sec, self, self.preserve_comments)
            parent.children[section.title] = section
            last_by_level[section.level] = section
        return root


class Section(Node):
    def __init__(self, raw, root, preserve_comments=False):
        super().__init__(raw, root, preserve_comments)
        self.title = strip_style(self.raw.title)
        self.level = self.raw.level
        self.children = ordered_dict()

    def __repr__(self):
        return f'<{type(self).__name__}[{self.level}: {self.title}]>'

    def __getitem__(self, item):
        return self.children[item]

    def __iter__(self):
        yield from self.children.values()

    @property
    def depth(self):
        if self.children:
            return max(c.depth for c in self.children.values()) + 1
        return 0

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

    @cached_property
    def content(self):
        if self.level == 0:                                 # without .string here, .tags() returns the full page's tags
            return as_node(self.raw.string.strip(), self.root, self.preserve_comments)
        return as_node(self.raw.contents.strip(), self.root, self.preserve_comments)    # chop off the header

    def pprint(self, mode='reprs', indent='', recurse=True):
        if mode == 'content':
            print(self.raw.pformat())
            if recurse:
                for child in self.children.values():
                    child.pprint(mode, recurse=recurse)
        elif mode == 'headers':
            print(f'{indent}{"=" * self.level}{self.title}{"=" * self.level}')
            if recurse:
                for child in self.children.values():
                    child.pprint(mode, indent=indent + ' ' * 4, recurse=recurse)
        elif mode == 'reprs':
            print(f'{indent}{self}')
            if recurse:
                for child in self.children.values():
                    child.pprint(mode, indent=indent + ' ' * 4, recurse=recurse)


WTP_TYPE_METHOD_NODE_MAP = {
    'Template': 'templates',
    'Comment': 'comments',
    'ExtensionTag': 'tags',
    'Tag': 'tags',              # Requires .tags() to be called before being in ._type_to_spans
    'Table': 'tables',          # Requires .tables to be accessed before being in ._type_to_spans
    'WikiList': 'lists',        # Requires .lists() to be called before being in ._type_to_spans
}
WTP_ACCESS_FIRST = {'Tag', 'Table', 'WikiList'}
WTP_ATTR_TO_NODE_MAP = {'tags': BasicNode, 'templates': Template, 'tables': Table, 'lists': List, 'comments': BasicNode}


def short_repr(text):
    text = str(text)
    if len(text) <= 50:
        return repr(text)
    else:
        return repr(f'{text[:24]}...{text[-23:]}')


def wiki_attr_values(wiki_text, attr, known_values=None):
    if known_values:
        try:
            return known_values[attr]
        except KeyError:
            pass
    value = getattr(wiki_text, attr)
    return value() if hasattr(value, '__call__') else value


def as_node(wiki_text, root=None, preserve_comments=False, strict_tags=False):
    """
    :param str|WikiText wiki_text: The content to process
    :param Root root: The root node that is an ancestor of this node
    :param bool preserve_comments: Whether HTML comments should be dropped or included in parsed nodes
    :param bool strict_tags: If True, require tags to be either self-closing or have a matching closing tag to consider
      it a tag, otherwise classify it as a string.
    :return Node: A :class:`Node` or subclass thereof
    """
    if wiki_text is None:
        return wiki_text
    if isinstance(wiki_text, str):
        wiki_text = WikiText(wiki_text)

    node_start = wiki_text.span[0]
    values = {}
    first = None
    first_attr = None
    for wtp_type, attr in WTP_TYPE_METHOD_NODE_MAP.items():
        # log.debug(f'Types available: {wiki_text._type_to_spans.keys()}; ExtensionTags: {wiki_text._type_to_spans["ExtensionTag"]}')
        if wtp_type in WTP_ACCESS_FIRST:
            values[attr] = wiki_attr_values(wiki_text, attr)
        type_spans = iter(wiki_text._subspans(wtp_type))
        span = next(type_spans, None)
        if span and strict_tags and attr == 'tags':
            obj_str = wiki_attr_values(wiki_text, attr, values)[0].string
            close_str = f'</{obj_str[1:-1]}>'
            if not obj_str.endswith('/>') and close_str not in wiki_text:
                log.log(9, f'Treating {obj_str!r} as a string because strict_tags=True')
                span = next(type_spans, None)

        if span:
            # log.debug(f'Found {wtp_type:>8s} @ {span}')
            start = span[0]
            if first is None or first > start:
                # if first is None:
                #     log.debug(f'  > It was the first object found')
                # else:
                #     log.debug(f'  > It came before the previously discovered first object')
                first = start
                first_attr = attr
                if first == node_start:
                    # log.debug(f'    > It is definitely the first object')
                    break

    try:
        if first_attr == 'tags' and len(values[first_attr]) == 1 and values[first_attr][0].name == 'small':
            first_attr = None   # Treat it like a String
    except (TypeError, KeyError):
        pass

    if first_attr:
        raw_objs = wiki_attr_values(wiki_text, first_attr, values)
        drop = first_attr == 'comments' and not preserve_comments
        # if first > 10:
        #     obj_area = f'{wiki_text(first-10, first)}{colored(wiki_text(first), "red")}{wiki_text(first+1, first+10)}'
        # else:
        #     obj_area = f'{colored(wiki_text(0), "red")}{wiki_text(1, 20)}'
        # log.debug(f'Found {first_attr:>9s} @ pos={first:>7,d} start={node_start:>7,d}  in [{short_repr(wiki_text)}]: [{obj_area}]')
        raw_obj = raw_objs[0]
        node = WTP_ATTR_TO_NODE_MAP[first_attr](raw_obj, root, preserve_comments)
        if raw_obj.string.strip() == wiki_text.string.strip():
            # log.debug(f'  > It was the only thing in this node: {node}')
            return None if drop else node

        compound = CompoundNode(wiki_text, root, preserve_comments)
        before, node_str, after = map(str.strip, wiki_text.string.partition(raw_obj.string))

        if before:
            # log.debug(f'  > It had something before it: [{short_repr(before)}]')
            before_node = as_node(before, root, preserve_comments)
            if drop and not after:
                return before_node
            elif type(before_node) is CompoundNode:             # It was not a subclass that stands on its own
                compound.children.extend(before_node.children)
            elif before_node is not None:
                compound.children.append(before_node)

        if not drop:
            compound.children.append(node)

        if after:
            # log.debug(f'  > It had something after it: [{short_repr(after)}]')
            after_node = as_node(after, root, preserve_comments)
            if drop and not before:
                return after_node
            elif type(after_node) is CompoundNode:
                compound.children.extend(after_node.children)
            elif after_node is None:
                if len(compound) == 1:
                    return compound[0]
            else:
                compound.children.append(after_node)

        return compound
    else:
        # log.debug(f'No complex objs found in [{wiki_text(0, 30)!r}]')
        links = wiki_text.wikilinks
        if not links:
            return String(wiki_text, root)
        elif strip_style(links[0].string) == strip_style(wiki_text.string):
            return Link(wiki_text, root)

        return MixedNode(wiki_text, root)


def extract_links(raw, root=None):
    try:
        end_pat = extract_links._end_pat
        start_pat = extract_links._start_pat
    except AttributeError:
        end_pat = extract_links._end_pat = re.compile(r'^(.*?)([\'"]+)$', re.DOTALL)
        start_pat = extract_links._start_pat = re.compile(r'^([\'"]+)(.*)$', re.DOTALL)

    content = []
    raw_str = raw.string.strip()
    for link in raw.wikilinks:
        before, link_text, raw_str = map(str.strip, raw_str.partition(link.string))
        # log.debug(f'Split raw into:\nbefore={before!r}\nlink={link_text!r}\nafter={raw_str!r}\n')
        if before and raw_str:
            bm = end_pat.match(before)
            if bm:
                # log.debug(f' > Found quotes at the end of before: {bm.group(2)}')
                am = start_pat.match(raw_str)
                if am:
                    # log.debug(f' > Found quotes at the beginning of after: {am.group(1)}')
                    before = bm.group(1).strip()
                    link_text = f'{bm.group(2)}{link_text}{am.group(1)}'
                    raw_str = am.group(2).strip()
        if before:
            content.append(String(before, root))
        content.append(Link(WikiText(link_text), root))

    if raw_str:
        content.append(String(raw_str, root))
    return content
