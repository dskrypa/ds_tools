from __future__ import annotations

import ast
import logging
from argparse import ArgumentParser
from ast import NodeVisitor, AST, Assign, Call, For, Attribute, Name, withitem
from collections import ChainMap
from functools import partial
from inspect import Signature, BoundArguments
from pathlib import Path
from typing import Callable, Collection, TypeVar, Generic, Type

from ds_tools.caching.decorators import cached_property
from ds_tools.argparsing.argparser import ArgParser as CustomArgParser
from .ast_utils import get_name_repr, imp_names

__all__ = ['ParserArg', 'ParserConstant', 'ArgGroup', 'MutuallyExclusiveGroup', 'ArgParser', 'SubParser', 'Script']
log = logging.getLogger(__name__)

InitNode = Call | Assign | withitem


class Scoped:
    def __init__(self, func: Callable, name: str):
        self.func = func
        self.name = name

    def _scoped(self, inst: ScriptVisitor, *args, **kwargs):
        inst.scopes = inst.scopes.new_child()
        inst.context.append(self.name)
        try:
            self.func(inst, *args, **kwargs)
        finally:
            inst.context.pop()
            inst.scopes = inst.scopes.parents

    def __get__(self, instance, owner):
        if instance is None:
            return self
        return partial(self._scoped, instance)


def scoped(name: str):
    return partial(Scoped, name=name)


class ScriptVisitor(NodeVisitor):
    context: list[str]

    def __init__(self, script: Script, parser_cls_names: Collection[str] = ()):
        self.script = script
        self.parsers = []
        self._parser_cls_names = parser_cls_names
        self.scopes = ChainMap()
        self.context = ['global']
        _ = self.mod_canonical_map

    # region Imports

    @cached_property
    def mod_canonical_map(self) -> dict[str, bool]:
        mod_canonical_map = {'argparse': 'ArgumentParser'}
        if extras := self._parser_cls_names:
            for name in set(extras):
                try:
                    mod, canonical = name.rsplit('.', 1)
                except ValueError:
                    self.scopes[name] = partial(self.script.add_parser, False)
                else:
                    mod_canonical_map[mod] = canonical
        return mod_canonical_map

    def visit_Import(self, node):
        for name, as_name in imp_names(node):
            if canonical := self.mod_canonical_map.get(name):
                self.scopes[f'{as_name}.{canonical}'] = partial(self.script.add_parser, name == 'argparse')

    def visit_ImportFrom(self, node):
        module = node.module
        if canonical := self.mod_canonical_map.get(module):
            for name, as_name in imp_names(node):
                if name == canonical:
                    self.scopes[as_name] = partial(self.script.add_parser, module == 'argparse')

    # endregion

    # region Scope Changes

    @scoped('function')
    def visit_FunctionDef(self, node):
        self.generic_visit(node)

    visit_AsyncFunctionDef = visit_FunctionDef
    visit_Lambda = visit_FunctionDef

    @scoped('class')
    def visit_ClassDef(self, node):
        self.generic_visit(node)

    @scoped('for')
    def visit_For(self, node: For):
        if not isinstance(node.target, Name):
            self.generic_visit(node)
            return

        loop_var = node.target.id
        try:
            ele_names = [get_name_repr(ele) for ele in node.iter.elts]  # noqa
        except (AttributeError, TypeError):
            ele_names = ()

        visited_any = False
        for name in ele_names:
            if func := self.scopes.get(name):
                visited_any = True
                self.scopes[loop_var] = func
                self.generic_visit(node)

        if not visited_any:
            self.generic_visit(node)

    visit_AsyncFor = visit_For

    @scoped('while')
    def visit_While(self, node):
        self.generic_visit(node)

    # endregion

    def get_func(self, name: str | AST):
        if not isinstance(name, str):
            name = get_name_repr(name)
        try:
            return self.scopes[name]
        except KeyError:
            pass
        try:
            obj_name, attr = name.rsplit('.', 1)
        except ValueError:
            return None
        # log.debug(f'Looking up {obj_name=}, {attr=}')
        try:
            obj = self.scopes[obj_name]
        except KeyError:
            return None
        try:
            can_call = attr in obj.visit_funcs
        except (AttributeError, TypeError):
            # log.debug(f'  > Found {obj=}')
            return None
        # log.debug(f'  > Found {obj=} {can_call=}')
        return getattr(obj, attr) if can_call else None

    def visit_withitem(self, item):
        context_expr = item.context_expr
        if func := self.get_func(context_expr):
            call = context_expr if isinstance(context_expr, Call) else None
            result = func(item, call)
            if as_name := item.optional_vars:
                self.scopes[get_name_repr(as_name)] = result

    def visit_Assign(self, node: Assign):
        value = node.value
        if isinstance(value, (Attribute, Name)):  # Assigning an alias to a variable
            if val_obj := self.get_func(value):
                for target in node.targets:
                    self.scopes[get_name_repr(target)] = val_obj
        elif isinstance(value, Call):
            if func := self.get_func(value.func):
                result = func(node, value)
                for target in node.targets:
                    self.scopes[get_name_repr(target)] = result

    def visit_Call(self, node: Call):
        if func := self.get_func(node.func):
            func(node, node)


class visit_func:
    __slots__ = ('func',)

    def __init__(self, func):
        self.func = func

    def __set_name__(self, owner: Type[AstCallable], name: str):
        owner._add_visit_func(name)
        setattr(owner, name, self.func)  # There's no need to keep the descriptor - replace self with func

    def __get__(self, instance, owner):
        # This will never actually be called, but it makes PyCharm happy
        return self if instance is None else partial(self.func, instance)


class AstCallable:
    wraps: Callable
    visit_funcs = set()
    _sig: Signature = None

    @classmethod
    def _add_visit_func(cls, name: str):
        try:
            parent_visit_funcs = cls.__base__.visit_funcs  # noqa
        except AttributeError:
            pass
        else:  # Note: __init_subclass__ is called after __set_name__ is called for members
            if parent_visit_funcs is cls.visit_funcs:
                cls.visit_funcs = cls.visit_funcs.copy()
        cls.visit_funcs.add(name)

    def __init_subclass__(cls, wraps: Callable = None, **kwargs):
        super().__init_subclass__(**kwargs)
        if wraps:
            cls.wraps = wraps

    def __init__(self, init_node: InitNode, parent: AstCallable | Script, call_node: Call = None):
        self.init_node = init_node
        if not call_node:
            call_node = init_node.value if isinstance(init_node, Assign) else init_node  # type: Call
        self.call_node = call_node
        self.call_args = call_node.args
        self.call_kwargs = call_node.keywords
        self.parent = parent
        self.names = set()

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
        print(f'{" " * indent} - {self!r}')


class ParserArg(AstCallable, wraps=ArgumentParser.add_argument):
    parent: ArgCollection


class ParserConstant(AstCallable):
    parent: ArgParser


AC = TypeVar('AC', bound=AstCallable)


class AddVisitedChild(Generic[AC]):
    __slots__ = ('child_cls', 'list_attr')

    def __init__(self, child_cls: Type[AC], attr: str):
        self.child_cls = child_cls
        self.list_attr = attr

    def __set_name__(self, owner: Type[ArgCollection], name: str):
        owner._add_visit_func(name)

    def __get__(self, instance, owner) -> Callable[[InitNode, Call], AC]:
        if instance is None:
            return self  # noqa
        return partial(instance._add_child, self.child_cls, getattr(instance, self.list_attr))  # noqa


class ArgCollection(AstCallable):
    parent: ArgCollection | Script
    _children = ('args', 'groups')
    args: list[ParserArg]
    groups: list[ArgGroup]
    add_argument = AddVisitedChild(ParserArg, 'args')

    def __init_subclass__(cls, children: Collection[str] = (), **kwargs):
        super().__init_subclass__(**kwargs)
        if children:
            cls._children = (*cls._children, *children)

    def __init__(self, init_node: InitNode, parent: AstCallable | Script, call_node: Call = None):
        super().__init__(init_node, parent, call_node)
        self.args = []
        self.groups = []

    @cached_property
    def is_stdlib(self) -> bool:
        parent = self.parent
        while parent:
            try:
                return parent.is_stdlib
            except AttributeError:
                parent = parent.parent
        return True

    def __repr__(self) -> str:
        stdlib = self.is_stdlib
        return f'<{self.__class__.__name__}[{stdlib=}]: ``{" = ".join(sorted(self.names))} = {self.init_call_repr()}``>'

    def _add_child(self, cls: Type[AC], container: list[AC], node: InitNode, call: Call) -> AC:
        child = cls(node, self, call)
        container.append(child)
        return child

    @visit_func
    def add_mutually_exclusive_group(self, node: InitNode, call: Call):
        return self._add_child(MutuallyExclusiveGroup, self.groups, node, call)

    @visit_func
    def add_argument_group(self, node: InitNode, call: Call):
        return self._add_child(ArgGroup, self.groups, node, call)

    # region Output Methods

    def pprint(self, indent: int = 0):
        prefix = ' ' * indent
        print(f'{prefix} + {self!r}:')
        indent += 3
        for attr in self._children:
            if values := getattr(self, attr):
                for value in values:
                    value.pprint(indent)

    # endregion


class ArgGroup(ArgCollection, wraps=ArgumentParser.add_argument_group):
    pass


class MutuallyExclusiveGroup(ArgGroup, wraps=ArgumentParser.add_mutually_exclusive_group):
    pass


class SubparsersAction(AstCallable):
    parent: ArgParser

    @visit_func
    def add_parser(self, node: InitNode, call: Call):
        return self.parent.add_subparser(node, call, True)


class ArgParser(ArgCollection, wraps=ArgumentParser, children=('sub_parsers', 'constants')):
    is_stdlib: bool = True
    sub_parsers: list[SubParser]
    constants: list[ParserConstant]
    add_subparsers = AddVisitedChild(SubparsersAction, '_subparsers_actions')
    add_constant = AddVisitedChild(ParserConstant, 'constants')

    def __init__(
        self, init_node: InitNode, parent: AstCallable | Script, call_node: Call = None, is_stdlib: bool = True
    ):
        super().__init__(init_node, parent, call_node)
        self._subparsers_actions = []
        self.sub_parsers = []
        self.constants = []
        self.is_stdlib = is_stdlib

    def __repr__(self) -> str:
        stdlib = self.is_stdlib
        sub_parsers = len(self.sub_parsers)
        assign_repr = f'``{" = ".join(sorted(self.names))} = {self.init_call_repr()}``'
        return f'<{self.__class__.__name__}[{stdlib=}, {sub_parsers=}]: {assign_repr}>'

    @visit_func
    def add_subparser(self, node: InitNode, call: Call, stdlib: bool = False):
        sub_parser = self._add_child(SubParser, self.sub_parsers, node, call)
        if not stdlib:
            sub_parser.wraps = CustomArgParser.add_subparser
        return sub_parser


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
        self._parser_cls_names = parser_cls_names
        self._parsers = []

    def __repr__(self) -> str:
        parsers = len(self.parsers)
        return f'<{self.__class__.__name__}[{parsers=} @ {self.path.as_posix()}]>'

    def add_parser(self, stdlib: bool, node: InitNode, call: Call | None) -> ArgParser:
        parser = ArgParser(node, self, call, stdlib)
        self._parsers.append(parser)
        return parser

    @cached_property
    def parsers(self) -> list[ArgParser]:
        visitor = ScriptVisitor(self, self._parser_cls_names)
        visitor.visit(self.root_node)
        return self._parsers
