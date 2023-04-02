from __future__ import annotations

import ast
import logging
from argparse import ArgumentParser
from ast import AST, Assign, Call, With
from inspect import Signature, BoundArguments
from pathlib import Path
from typing import Callable, Collection, Iterator, TypeVar, Mapping

from ds_tools.caching.decorators import cached_property
from ds_tools.argparsing.argparser import ArgParser as CustomArgParser
from .ast_utils import get_name_repr, imp_names, find_calls_by_name, get_assigned_alias

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

    def __init__(self, root_node: AST, init_node: InitNode, parent: AstCallable | Script, call_node: Call = None):
        self.init_node = init_node
        if not call_node:
            call_node = init_node.value if isinstance(init_node, Assign) else init_node  # type: Call
        self.call_node = call_node
        self.call_args = call_node.args
        self.call_kwargs = call_node.keywords
        self.root_node = root_node
        self.parent = parent

    def __repr__(self) -> str:
        return f'<{self.__class__.__name__}[{self.init_call_repr()}]>'

    @classmethod
    def _signature(cls) -> Signature:
        if not (sig := cls._sig):
            cls._sig = sig = Signature.from_callable(cls.wraps)
        return sig

    @property
    def signature(self) -> Signature:
        return self._signature()

    @cached_property
    def names(self) -> set[str]:
        try:
            return {get_name_repr(target) for target in self.init_node.targets}
        except AttributeError:
            pass

        names = set()
        if isinstance(self.init_node, With):
            for item in self.init_node.items:
                if self.init_func_name == get_name_repr(item.context_expr) and item.optional_vars:
                    names.add(get_name_repr(item.optional_vars))
        else:
            log.debug(f'Unable to determine assigned names for {self!r}')
        return names

    # region Find Children

    def get_func_names(self, canonical: str) -> set[str]:
        func_names = {f'{n}.{canonical}' for n in self.names}
        for node in ast.walk(self.root_node):
            if alias := get_assigned_alias(node, func_names):
                func_names.add(alias)
        return func_names

    def find_children(self, cls: Callable[..., AC], func_name: str) -> Iterator[AC]:
        for node, root, call, _ in find_calls_by_name(self.root_node, self.get_func_names(func_name)):
            yield cls(root, node, self, call)

    # endregion

    # region Initialization Call

    @cached_property
    def init_func_name(self) -> str:
        """The name or alias of the function/callable that was used to initialize this object"""
        return get_name_repr(self.call_node.func)

    @cached_property
    def _init_func_bound(self) -> BoundArguments:
        return self.signature.bind('self', *self.call_args, **{kw.arg: kw.value for kw in self.call_kwargs})

    @cached_property
    def init_func_args(self) -> list[str]:
        try:
            args = self._init_func_bound.args[1:]
        except (TypeError, AttributeError):  # No wraps func
            args = self.call_args
        return [ast.unparse(arg) for arg in args]

    @cached_property
    def init_func_kwargs(self) -> dict[str, str]:
        try:
            kwargs = self._init_func_bound.kwargs
        except (TypeError, AttributeError):  # No wraps func
            kwargs = {kw.arg: kw.value for kw in self.call_kwargs}
        return {key: ast.unparse(val) for key, val in kwargs.items()}

    def init_call_repr(self) -> str:
        arg_str = ', '.join(self.init_func_args)
        if kw_str := ', '.join(f'{k}={v}' for k, v in self.init_func_kwargs.items()):
            arg_str = kw_str if not arg_str else (arg_str + ', ' + kw_str)
        return f'{self.init_func_name}({arg_str})'

    # endregion

    def pprint(self, indent: int = 0):
        # print(f'{" " * indent}   - {self!r}')
        print(f'{" " * indent} - {self!r}')


class ParserArg(AstCallable, wraps=ArgumentParser.add_argument):
    parent: ArgCollection


class ParserConstant(AstCallable):
    parent: ArgParser


AC = TypeVar('AC', bound=AstCallable)


class ArgCollection(AstCallable):
    parent: ArgCollection | Script
    _children = {'args': 'Arguments', 'groups': 'Groups'}

    def __init_subclass__(cls, children: Mapping[str, str] = None, **kwargs):
        super().__init_subclass__(**kwargs)
        if children:
            cls._children = cls._children | children

    @cached_property
    def is_stdlib(self) -> bool:
        parent = self.parent
        if isinstance(parent, Script):
            return parent.parser_cls_names[self.init_func_name]
        while parent:
            try:
                return parent.is_stdlib
            except AttributeError:
                parent = parent.parent
        return True

    def __repr__(self) -> str:
        stdlib = self.is_stdlib
        return f'<{self.__class__.__name__}[{stdlib=}]: ``{" = ".join(sorted(self.names))} = {self.init_call_repr()}``>'

    @cached_property
    def args(self) -> list[ParserArg]:
        return list(self.find_children(ParserArg, 'add_argument'))

    @cached_property
    def groups(self) -> list[ArgGroup]:
        types = (('add_mutually_exclusive_group', MutuallyExclusiveGroup), ('add_argument_group', ArgGroup))
        return [group for name, cls in types for group in self.find_children(cls, name)]

    # region Output Methods

    def pprint(self, indent: int = 0):
        prefix = ' ' * indent
        print(f'{prefix} + {self!r}:')
        indent += 3
        for attr, header in self._children.items():
            if values := getattr(self, attr):
                for value in values:
                    value.pprint(indent)

    # endregion


class ArgGroup(ArgCollection, wraps=ArgumentParser.add_argument_group):
    pass


class MutuallyExclusiveGroup(ArgGroup, wraps=ArgumentParser.add_mutually_exclusive_group):
    pass


class ArgParser(ArgCollection, wraps=ArgumentParser, children={'sub_parsers': 'Subparsers', 'constants': 'Constants'}):
    def __repr__(self) -> str:
        stdlib = self.is_stdlib
        sub_parsers = len(self.sub_parsers)
        assign_repr = f'``{" = ".join(sorted(self.names))} = {self.init_call_repr()}``'
        return f'<{self.__class__.__name__}[{stdlib=}, {sub_parsers=}]: {assign_repr}>'

    @cached_property
    def sub_parsers(self) -> list[SubParser]:
        sub_parsers = []
        for subparser_action in self.find_children(AstCallable, 'add_subparsers'):
            sub_parsers.extend(subparser_action.find_children(SubParser, 'add_parser'))

        if not self.is_stdlib:
            for sub_parser in self.find_children(SubParser, 'add_subparser'):
                sub_parser.wraps = CustomArgParser.add_subparser
                sub_parsers.append(sub_parser)

        return sub_parsers

    @cached_property
    def constants(self) -> list[ParserConstant]:
        return [] if self.is_stdlib else list(self.find_children(ParserConstant, 'add_constant'))


class SubParser(ArgParser):
    @property
    def signature(self) -> Signature:
        if self.is_stdlib:
            return self._signature()
        return Signature.from_callable(self.wraps)


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
    def parser_cls_names(self) -> dict[str, bool]:
        stdlib_mod, stdlib_canonical = 'argparse', 'ArgumentParser'
        mod_canonical_map = {stdlib_mod: stdlib_canonical}
        name_stdlib_map = {}
        if extras := self._parser_cls_names:
            for name in set(extras):
                try:
                    mod, canonical = name.rsplit('.', 1)
                except ValueError:
                    name_stdlib_map[name] = False
                else:
                    mod_canonical_map[mod] = canonical

        for imp in self.imports:
            try:
                module = imp.module
            except AttributeError:  # it was an Import, not an ImportFrom
                for name, as_name in imp_names(imp):
                    if canonical := mod_canonical_map.get(name):
                        name_stdlib_map[f'{as_name}.{canonical}'] = name == stdlib_mod
            else:  # it was an ImportFrom
                if canonical := mod_canonical_map.get(module):
                    for name, as_name in imp_names(imp):
                        if name == canonical:
                            name_stdlib_map[as_name] = module == stdlib_mod

        return name_stdlib_map

    @cached_property
    def parsers(self) -> list[ArgParser]:
        return [
            ArgParser(root, node, self)
            for node, root, _, _ in find_calls_by_name(self.root_node, self.parser_cls_names, True)
        ]
