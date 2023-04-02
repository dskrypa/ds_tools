from __future__ import annotations

import ast
import logging
from ast import AST, Assign, Call, Attribute, Name, With
from collections import deque
from typing import Callable, TypeVar, Iterator, Collection, Any

__all__ = ['find_nodes', 'dump', 'get_name_repr', 'imp_names', 'find_calls_by_name', 'get_assigned_alias']
log = logging.getLogger(__name__)

T = TypeVar('T')


def find_calls_by_name(
    root_node: AST, names: Collection[str], strict_assigns: bool = False
) -> Iterator[tuple[T, AST, Call, str]]:
    remaining = deque([root_node])
    while remaining:
        root = remaining.popleft()
        nodes = list(ast.iter_child_nodes(root))
        found_any = False
        for node in nodes:
            if strict_assigns and (not isinstance(node, Assign) or not isinstance(node.value, Call)):
                continue

            for call in _iter_calls(node):
                if (name := get_name_repr(call)) in names:
                    found_any = True
                    yield node, root, call, name

        if not found_any:
            remaining.extend(nodes)


def _iter_calls(node: AST) -> Iterator[Call]:
    if isinstance(node, With):
        for item in node.items:
            if isinstance(item.context_expr, Call):
                yield item.context_expr
        return
    elif isinstance(node, Assign):
        node = node.value

    if isinstance(node, Call):
        yield node


def get_assigned_alias(node: AST, names: Collection[str]) -> str | None:
    if not isinstance(node, Assign):
        return None
    node = node.value
    if not isinstance(node, (Attribute, Name)):
        return None
    try:
        name = get_name_repr(node)
    except (AttributeError, TypeError):
        return None
    return name if name in names else None


def find_nodes(root_node: AST, is_match: Callable[[AST], bool | Any]) -> Iterator[tuple[T, AST]]:
    remaining = deque([root_node])
    while remaining:
        root = remaining.popleft()

        nodes = list(ast.iter_child_nodes(root))
        found_any = False
        for node in nodes:
            if is_match(node):
                found_any = True
                yield node, root

        if not found_any:
            remaining.extend(nodes)


def get_name_repr(node: AST) -> str:
    if isinstance(node, Call):
        node = node.func

    if isinstance(node, Name):
        return node.id
    elif isinstance(node, Attribute):
        return f'{get_name_repr(node.value)}.{node.attr}'  # noqa
    elif isinstance(node, AST):
        return ast.unparse(node)
    else:
        raise TypeError(f'Only AST nodes are supported - found {node.__class__.__name__}')


def imp_names(imp: ast.Import | ast.ImportFrom) -> Iterator[tuple[str, str]]:
    for alias in imp.names:
        name = alias.name
        as_name = alias.asname or name
        yield name, as_name


# region AST dump


def dump(node, skip_outer_module: bool = True):
    """Return a formatted dump of the tree in node.  This is mainly useful for debugging purposes."""
    if skip_outer_module and isinstance(node, ast.Module) and len(node.body) == 1:
        node = node.body[0]
    return _format(node)[0]


def _format(node: AST, level: int = 0, indent: str = '    '):
    suffix = '\n' + indent * level
    level += 1
    prefix, sep = '\n' + indent * level, ',\n' + indent * level
    if isinstance(node, list):
        if not node:
            return '[]', True, 0
        all_simple, nested_count, parts = True, 0, []
        for n in node:
            n_str, simple, nested = _format(n, level)
            nested_count += nested
            all_simple &= simple and not nested
            parts.append(n_str)

        node_rep = f'[{", ".join(parts)}]' if all_simple else f'[{prefix}{sep.join(parts)}{suffix}]'
        return node_rep, False, nested_count + 1
    elif not isinstance(node, AST):
        return repr(node), True, 0

    cls, all_simple, nested_count, args = type(node), True, 0, []
    for name in node._fields:
        try:
            value = getattr(node, name)
        except AttributeError:
            continue
        if value is None and getattr(cls, name, ...) is None:
            continue
        value, simple, nested = _format(value, level)
        nested_count += nested
        all_simple &= simple
        args.append(f'{name}={value}')

    if not args:
        return f'{cls.__name__}()', True, 0
    elif all_simple and (not nested_count or (len(args) < 3 and nested_count < 2)):
        return f'{cls.__name__}({", ".join(args)})', True, nested_count + 1
    formatted = f'{cls.__name__}({prefix}{sep.join(args)}{suffix})'
    return formatted, '\n' not in formatted, nested_count + 1


# endregion
