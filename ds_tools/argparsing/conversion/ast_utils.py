from __future__ import annotations

import ast
import logging
from ast import AST, Assign, Call, Attribute, Name
from collections import deque
from typing import Callable, TypeVar, Type, Iterator, Collection, Any

__all__ = ['get_match_name', 'find_nodes', 'dump', 'get_name_repr', 'imp_names']
log = logging.getLogger(__name__)

T = TypeVar('T')


def get_match_name(
    node: AST, names: Collection[str], exp_type: Type[AST] | tuple[Type[AST], ...], val_type: Type[AST] = None
) -> str | None:
    if not isinstance(node, exp_type) or (val_type is not None and not isinstance(node.value, val_type)):  # noqa
        return None
    elif isinstance(node, Assign):
        target = node.value
        if val_type and val_type is Call:
            target = target.func  # noqa
    elif isinstance(node, Call):
        target = node.func
    else:
        raise TypeError(type(node).__name__)

    if not isinstance(target, (Attribute, Name)):
        return None

    try:
        name = get_name_repr(target)
    except (AttributeError, TypeError):
        return None

    return name if name in names else None


def find_nodes(root_node: AST, is_match: Callable[[AST], bool | Any]) -> Iterator[tuple[T, AST]]:
    remaining = deque([root_node])
    while remaining:
        root = remaining.popleft()
        nodes = list(ast.iter_child_nodes(root))
        if matching_node := next((n for n in nodes if is_match(n)), None):
            yield matching_node, root
        else:
            remaining.extend(nodes)


def get_name_repr(node: Attribute | Name) -> str:
    if isinstance(node, Call):
        node = node.func

    if isinstance(node, Name):
        return node.id
    elif isinstance(node, Attribute):
        return f'{get_name_repr(node.value)}.{node.attr}'  # noqa
    elif isinstance(node, AST):
        raise TypeError(f'Unexpected type for node={ast.dump(node)}')
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
