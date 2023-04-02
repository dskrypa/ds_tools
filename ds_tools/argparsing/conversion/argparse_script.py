from __future__ import annotations

import ast
import logging
from argparse import ArgumentParser
from ast import AST, Assign, Call
from functools import partial
from inspect import Signature, BoundArguments
from pathlib import Path
from typing import Callable, Collection

from ds_tools.caching.decorators import cached_property
from .ast_utils import get_match_name, find_nodes, get_name_repr, imp_names

__all__ = ['Script', 'ParserArg', 'ArgGroup', 'MutuallyExclusiveGroup', 'ArgParser']
log = logging.getLogger(__name__)

InitNode = Call | Assign


class AstCallable:
    wraps: Callable
    _sig: Signature = None

    def __init_subclass__(cls, wraps: Callable = None, **kwargs):
        super().__init_subclass__(**kwargs)
        if wraps:
            cls.wraps = wraps

    def __init__(self, init_node: InitNode):
        self.init_node = init_node
        self.call_node = call_node = init_node.value if isinstance(init_node, Assign) else init_node  # type: Call
        self.call_args = call_node.args
        self.call_kwargs = call_node.keywords

    @classmethod
    def _signature(cls) -> Signature:
        if not (sig := cls._sig):
            cls._sig = sig = Signature.from_callable(cls.wraps)
        return sig

    @cached_property
    def init_func_name(self) -> str:
        """The name or alias of the function/callable that was used to initialize this object"""
        return get_name_repr(self.call_node.func)  # noqa

    @cached_property
    def _init_func_bound(self) -> BoundArguments:
        return self._signature().bind('self', *self.call_args, **{kw.arg: kw.value for kw in self.call_kwargs})

    @cached_property
    def init_func_args(self) -> list[str]:
        # return [_normalize_arg_value(arg) for arg in self._init_func_bound.args[1:]]
        return [ast.unparse(arg) for arg in self._init_func_bound.args[1:]]

    @cached_property
    def init_func_kwargs(self) -> dict[str, str]:
        # return {key: _normalize_arg_value(val) for key, val in self._init_func_bound.kwargs.items()}
        return {key: ast.unparse(val) for key, val in self._init_func_bound.kwargs.items()}

    def init_call_repr(self) -> str:
        arg_str = ', '.join(self.init_func_args)
        if kw_str := ', '.join(f'{k}={v}' for k, v in self.init_func_kwargs.items()):
            arg_str = kw_str if not arg_str else (arg_str + ', ' + kw_str)
        return f'{self.init_func_name}({arg_str})'


class ParserArg(AstCallable, wraps=ArgumentParser.add_argument):
    def __init__(self, parent: ArgCollection, init_node: InitNode):
        super().__init__(init_node)
        self.parent = parent

    def __repr__(self) -> str:
        return f'<{self.__class__.__name__}[{self.init_call_repr()}]>'


class ArgCollection(AstCallable):
    def __init__(self, root_node: AST, init_node: InitNode, parent: ArgCollection = None, names: set[str] = None):
        super().__init__(init_node)
        self.root_node = root_node
        self.parent = parent
        self.names = names or {get_name_repr(target) for target in init_node.targets}  # noqa

    def __repr__(self) -> str:
        return f'<{self.__class__.__name__}: ``{" = ".join(sorted(self.names))} = {self.init_call_repr()}``>'

    # region Func Names

    def _get_func_names(self, canonical: str) -> set[str]:
        func_names = {f'{n}.{canonical}' for n in self.names}
        for node in ast.walk(self.root_node):
            if match := get_match_name(node, func_names, Assign):
                func_names.add(match)
        return func_names

    @cached_property
    def add_argument_func_names(self) -> set[str]:
        return self._get_func_names('add_argument')

    @cached_property
    def add_subparsers_names(self) -> set[str]:
        return self._get_func_names('add_subparsers')

    # endregion

    @cached_property
    def args(self) -> list[ParserArg]:
        is_add_argument = partial(get_match_name, names=self.add_argument_func_names, exp_type=(Assign, Call))
        return [ParserArg(self, call_node) for call_node, _ in find_nodes(self.root_node, is_add_argument)]

    @cached_property
    def groups(self) -> list[ArgGroup]:
        groups = []
        for name, cls in (('add_mutually_exclusive_group', MutuallyExclusiveGroup), ('add_argument_group', ArgGroup)):
            is_match = partial(get_match_name, names=self._get_func_names(name), exp_type=Assign, val_type=Call)
            for assign_node, root in find_nodes(self.root_node, is_match):
                groups.append(cls(root, assign_node, self))

        return groups

    # region Output Methods

    def pprint(self, indent: int = 0):
        prefix = ' ' * indent
        print(f'{prefix} - {self!r}:')
        if args := self.args:
            print(f'{prefix}    + Arguments:')
            for arg in args:
                print(f'{prefix}       - {arg!r}')
        else:
            print(f'{prefix}    + Arg func names: {self.add_argument_func_names}')

        if groups := self.groups:
            print(f'{prefix}    + Groups:')
            for group in groups:
                group.pprint(indent + 4)

    # endregion


class ArgGroup(ArgCollection, wraps=ArgumentParser.add_argument_group):
    pass


class MutuallyExclusiveGroup(ArgGroup, wraps=ArgumentParser.add_mutually_exclusive_group):
    pass


class ArgParser(ArgCollection, wraps=ArgumentParser):
    pass


class Script:
    def __init__(self, path: Path, parser_cls_names: Collection[str] = ()):
        self.path = path
        self.src_text = path.read_text()
        self.root_node = ast.parse(self.src_text, path.as_posix())
        self.imports = [node for node in ast.walk(self.root_node) if isinstance(node, (ast.Import, ast.ImportFrom))]
        self._parser_cls_names = parser_cls_names

    def __repr__(self) -> str:
        imports, parsers = len(self.imports), len(self.parsers)
        return f'<{self.__class__.__name__}[{imports=}, {parsers=} @ {self.path.as_posix()}]>'

    @cached_property
    def parser_cls_names(self) -> set[str]:
        mod_canonical_map = {'argparse': 'ArgumentParser'}
        names = set()
        if extras := self._parser_cls_names:
            for name in set(extras):
                try:
                    mod, canonical = name.rsplit('.', 1)
                except ValueError:
                    names.add(name)
                else:
                    mod_canonical_map[mod] = canonical

        # mod, canonical = 'argparse', 'ArgumentParser'
        for imp in self.imports:
            try:
                module = imp.module
            except AttributeError:  # it was an Import, not an ImportFrom
                # names.update(f'{as_name}.{canonical}' for name, as_name in imp_names(imp) if name == mod)
                for name, as_name in imp_names(imp):
                    if canonical := mod_canonical_map.get(name):
                        names.add(f'{as_name}.{canonical}')
            else:  # it was an ImportFrom
                # if module == mod:
                #     names.update(as_name for name, as_name in imp_names(imp) if name == canonical)
                if canonical := mod_canonical_map.get(module):
                    for name, as_name in imp_names(imp):
                        if name == canonical:
                            names.add(as_name)

        return names

    @cached_property
    def parsers(self) -> list[ArgParser]:
        is_parser = partial(get_match_name, names=self.parser_cls_names, exp_type=Assign, val_type=Call)
        return [ArgParser(root, assign_node) for assign_node, root in find_nodes(self.root_node, is_parser)]
