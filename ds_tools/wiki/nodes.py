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

from wikitextparser import WikiText

from ..compat import cached_property
from .utils import strip_style

__all__ = [
    'Node', 'BasicNode', 'CompoundNode', 'MappingNode', 'MixedNode', 'String', 'Link', 'List', 'Table', 'Template',
    'Root', 'Section', 'as_node', 'extract_links'
]
log = logging.getLogger(__name__)
PY_LT_37 = sys.version_info.major == 3 and sys.version_info.minor < 7
ordered_dict = OrderedDict if PY_LT_37 else dict            # 3.7+ dict retains insertion order; dict repr is cleaner


class Node:
    def __init__(self, raw):
        if isinstance(raw, str):
            raw = WikiText(raw)
        self.raw = raw

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

    def __iter__(self):
        yield from self.children

    def __len__(self):
        return len(self.children)


class MappingNode(CompoundNode):
    @cached_property
    def children(self):
        return ordered_dict()

    def items(self):
        return self.children.items()

    def keys(self):
        return self.children.keys()

    def values(self):
        return self.children.values()


class MixedNode(CompoundNode):
    """A node that contains text and links"""
    @cached_property
    def children(self):
        return extract_links(self.raw)


class String(BasicNode):
    def __init__(self, raw):
        super().__init__(raw)
        self.value = strip_style(self.raw.string)

    def __repr__(self):
        return f'<{type(self).__name__}({self.raw.string.strip()!r})>'

    def __str__(self):
        return self.value


class Link(BasicNode):
    def __init__(self, raw):
        super().__init__(raw)
        self.link = self.raw.wikilinks[0]
        self.title = self.link.title    # target = title + fragment
        self.text = self.link.text

    def __repr__(self):
        return f'<{type(self).__name__}({self.link.string!r})>'


class ListEntry(CompoundNode):
    def __init__(self, raw):
        super().__init__(raw)
        if type(self.raw) is WikiText:
            try:
                as_list = self.raw.lists()[0]
            except IndexError:
                self.value = as_node(self.raw)
                self._children = None
            else:
                self.value = as_node(as_list.items[0])
                try:
                    self._children = as_list.sublists()[0].string
                except IndexError:
                    self._children = None

    def __repr__(self):
        if self._children:
            return f'<{type(self).__name__}({self.value!r}, {self.children!r})>'
        return f'<{type(self).__name__}({self.value!r})>'

    @cached_property
    def children(self):
        if not self._children:
            return []
        children = [child[1:] for child in map(str.strip, self._children.splitlines())]
        return List('\n'.join(children)).children


class List(CompoundNode):
    def __init__(self, raw):
        super().__init__(raw)
        if type(self.raw) is WikiText:
            try:
                self.raw = self.raw.lists()[0]
            except IndexError as e:
                raise ValueError('Invalid wiki list value') from e

    @cached_property
    def children(self):
        return [ListEntry(val) for val in map(str.strip, self.raw.fullitems)]

    def iter_flat(self):
        for child in self.children:
            yield child
            if child.children:
                yield from child.children


class Table(CompoundNode):
    @cached_property
    def children(self):
        rows = iter(self.raw.cells())
        columns = [strip_style(cell.value) for cell in next(rows)]
        processed = [ordered_dict(zip(columns, map(as_node, row))) for row in rows]
        return processed


class Template(BasicNode):
    def __init__(self, raw):
        super().__init__(raw)
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
                return as_node(arg.value)
            return [as_node(a.value) for a in args]

        mapping = MappingNode(self.raw)
        for arg in args:
            key = strip_style(arg.name)
            mapping[key] = as_node(arg.value.strip())
        return mapping

    def __getitem__(self, item):
        if self.value is None:
            raise TypeError('Cannot index a template with no value')
        return self.value[item]


class Root(Node):
    # Children = sections
    def __init__(self, page_text):
        if isinstance(page_text, str):
            page_text = WikiText(page_text.replace('\xa0', ' '))
        super().__init__(page_text)

    @cached_property
    def sections(self):
        sections = iter(self.raw.sections)
        root = Section(next(sections))
        last_by_level = {0: root}
        for sec in sections:
            parent_lvl = sec.level - 1
            while parent_lvl > 0 and parent_lvl not in last_by_level:
                parent_lvl -= 1
            parent = last_by_level[parent_lvl]
            section = Section(sec)
            parent.children[section.title] = section
            last_by_level[section.level] = section
        return root


class Section(Node):
    def __init__(self, raw):
        super().__init__(raw)
        self.title = strip_style(raw.title)
        self.level = raw.level
        self.children = ordered_dict()

    def __repr__(self):
        return f'<{type(self).__name__}[{self.level}: {self.title}]>'

    def __getitem__(self, item):
        return self.children[item]

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
        if self.level == 0:
            return as_node(self.raw.string.strip())         # without .string here, .tags() returns the full page's tags
        return as_node(self.raw.string.partition('\n')[2])  # chop off the header

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


def short_repr(text):
    if len(text) <= 50:
        return repr(text)
    else:
        return repr(f'{text[:24]}...{text[-23:]}')


def as_node(wiki_text):
    """
    :param str|WikiText wiki_text: The content to process
    :return Node: A :class:`Node` of subclass thereof
    """
    if isinstance(wiki_text, str):
        wiki_text = WikiText(wiki_text)

    # TODO: If a given node is inside another node type, skip splitting on it until processing the inside of that node
    func_to_node = [
        ('tags', BasicNode), ('templates', Template), ('tables', Table), ('lists', List), ('comments', BasicNode)
    ]
    for name, node_cls in func_to_node:
        prop = getattr(wiki_text, name)
        raw_objs = prop() if hasattr(prop, '__call__') else prop
        # log.debug(f'Found {len(raw_objs):>03d} {name:>9s} in [{short_repr(wiki_text)}]')
        if raw_objs:
            node = node_cls(raw_objs[0])
            if node.raw.string.strip() == wiki_text.string.strip():
                # log.debug('  > It was the only thing in this node')
                return node
            compound = CompoundNode(wiki_text)
            before, node_str, after = map(str.strip, wiki_text.string.partition(node.raw.string))
            if before:
                # log.debug(f'  > It had something before it: [{short_repr(before)}]')
                before_node = as_node(before)
                if type(before_node) is CompoundNode:                   # It was not a subclass that stands on its own
                    compound.children.extend(before_node.children)
                else:
                    compound.children.append(before_node)

            compound.children.append(node)
            if after:
                # log.debug(f'  > It had something after it: [{short_repr(after)}]')
                after_node = as_node(after)
                if type(after_node) is CompoundNode:
                    compound.children.extend(after_node.children)
                else:
                    compound.children.append(after_node)

            return compound

    # log.debug(f'No complex objs found in [{wiki_text[:30]!r}]')
    links = wiki_text.wikilinks
    if not links:
        return String(wiki_text)
    elif len(links) == 1 or strip_style(links[0].string) == strip_style(wiki_text.string):
        # Reason for using or: (at least) file links support nested links, which are displayed as text under the file
        return Link(wiki_text)

    return MixedNode(wiki_text)


def extract_links(raw):
    try:
        end_pat = extract_links._end_pat
        start_pat = extract_links._start_pat
    except AttributeError:
        end_pat = extract_links._end_pat = re.compile(r'^(.*?)([\'"]+)$')
        start_pat = extract_links._start_pat = re.compile(r'^([\'"]+)(.*)$')

    content = []
    raw_str = raw.string.strip()
    for link in raw.wikilinks:
        before, link_text, raw_str = map(str.strip, raw_str.partition(link.string))
        if before and raw_str:
            bm = end_pat.match(before)
            if bm:
                am = start_pat.match(raw_str)
                if am:
                    before = bm.group(1).strip()
                    link_text = f'{bm.group(2)}{link_text}{am.group(1)}'
                    raw_str = am.group(2).strip()
        if before:
            content.append(String(before))
        content.append(Link(WikiText(link_text)))

    if raw_str:
        content.append(String(raw_str))
    return content
