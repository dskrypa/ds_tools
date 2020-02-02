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
# from ..output import colored
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

    def find_all(self, node_cls, recurse=False):
        for value in self:
            if isinstance(value, node_cls):
                yield value
            if recurse and isinstance(value, CompoundNode):
                yield from value.find_all(node_cls)


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
    def sub_list(self):
        if not self._children:
            return None
        return List('\n'.join(child[1:] for child in map(str.strip, self._children.splitlines())))

    @cached_property
    def children(self):
        sub_list = self.sub_list
        if not sub_list:
            return []
        return sub_list.children


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
            yield child.value
            if child.sub_list:
                yield from child.sub_list.iter_flat()


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

    def __getitem__(self, item):
        return self.sections[item]

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
        if self.level == 0:
            return as_node(self.raw.string.strip())         # without .string here, .tags() returns the full page's tags
        return as_node(self.raw.contents.strip())           # chop off the header

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
    if len(text) <= 50:
        return repr(text)
    else:
        return repr(f'{text[:24]}...{text[-23:]}')


def as_node(wiki_text):
    """
    :param str|WikiText wiki_text: The content to process
    :return Node: A :class:`Node` or subclass thereof
    """
    if isinstance(wiki_text, str):
        wiki_text = WikiText(wiki_text)

    node_start = wiki_text.span[0]
    values = {}
    first = None
    first_attr = None
    for wtp_type, attr in WTP_TYPE_METHOD_NODE_MAP.items():
        # log.debug(f'Types available: {wiki_text._type_to_spans.keys()}; ExtensionTags: {wiki_text._type_to_spans["ExtensionTag"]}')
        if wtp_type in WTP_ACCESS_FIRST:
            value = getattr(wiki_text, attr)
            value = value() if hasattr(value, '__call__') else value
            try:
                values[attr].extend(value)
            except KeyError:
                values[attr] = value
        span = next(iter(wiki_text._subspans(wtp_type)), None)
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
    except TypeError:           # Sometimes tag names are not available, it seems
        pass

    if first_attr:
        if first_attr in values:
            raw_objs = values[first_attr]
        else:
            value = getattr(wiki_text, first_attr)
            raw_objs = value() if hasattr(value, '__call__') else value

        # if first > 10:
        #     obj_area = f'{wiki_text[first-10:first]}{colored(wiki_text[first], "red")}{wiki_text[first+1:first+10]}'
        # else:
        #     obj_area = f'{colored(wiki_text[0], "red")}{wiki_text[1:20]}'
        # log.debug(f'Found {first_attr:>9s} @ pos={first:>7,d} start={node_start:>7,d}  in [{short_repr(wiki_text)}]: [{obj_area}]')
        raw_obj = raw_objs[0]
        node = WTP_ATTR_TO_NODE_MAP[first_attr](raw_obj)
        if node.raw.string.strip() == wiki_text.string.strip():
            # log.debug('  > It was the only thing in this node')
            return node
        compound = CompoundNode(wiki_text)
        before, node_str, after = map(str.strip, wiki_text.string.partition(node.raw.string))

        if before:
            # log.debug(f'  > It had something before it: [{short_repr(before)}]')
            before_node = as_node(before)
            if type(before_node) is CompoundNode:  # It was not a subclass that stands on its own
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
    else:
        # log.debug(f'No complex objs found in [{wiki_text[:30]!r}]')
        links = wiki_text.wikilinks
        if not links:
            return String(wiki_text)
        elif strip_style(links[0].string) == strip_style(wiki_text.string):
            return Link(wiki_text)

        return MixedNode(wiki_text)


def extract_links(raw):
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
            content.append(String(before))
        content.append(Link(WikiText(link_text)))

    if raw_str:
        content.append(String(raw_str))
    return content
