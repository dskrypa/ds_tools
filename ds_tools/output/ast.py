from ast import AST, Module

__all__ = ['dump']


def dump(node, skip_outer_module: bool = True):
    """Return a formatted dump of the tree in node.  This is mainly useful for debugging purposes."""
    if skip_outer_module and isinstance(node, Module) and len(node.body) == 1:
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
