from __future__ import annotations

import ast
import logging
import sys
from argparse import ArgumentParser
from ast import AST, Assign, Call, withitem
from functools import partial
from inspect import Signature, BoundArguments
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Collection, TypeVar, Generic, Type, Iterator

from ds_tools.caching.decorators import cached_property
from .ast_utils import get_name_repr
from .argparse_utils import ArgumentParser as _ArgumentParser, SubParsersAction as _SubParsersAction

if TYPE_CHECKING:
    from .visitor import TrackedRefMap, TrackedRef

__all__ = ['ParserArg', 'ArgGroup', 'MutuallyExclusiveGroup', 'AstArgumentParser', 'SubParser', 'Script']
log = logging.getLogger(__name__)

InitNode = Call | Assign | withitem
OptCall = Call | None
ParserCls = Type['AstArgumentParser']
ParserObj = TypeVar('ParserObj', bound='AstArgumentParser')
RepresentedCallable = TypeVar('RepresentedCallable', bound=Callable)
AC = TypeVar('AC', bound='AstCallable')
D = TypeVar('D')
_NotSet = object()


class Script:
    _parser_classes = {}

    def __init__(self, path: Path, smart_loop_handling: bool = True):
        self.path = path
        self.src_text = path.read_text()
        self.root_node = ast.parse(self.src_text, path.as_posix())
        self.smart_loop_handling = smart_loop_handling
        self._parsers = []

    def __repr__(self) -> str:
        parsers = len(self.parsers)
        return f'<{self.__class__.__name__}[{parsers=} @ {self.path.as_posix()}]>'

    @property
    def mod_cls_to_ast_cls_map(self) -> dict[str, dict[str, ParserCls]]:
        return self._parser_classes

    @classmethod
    def _register_parser(cls, real_cls: Type[ArgumentParser], ast_cls: ParserCls):
        module, name = real_cls.__module__, real_cls.__name__
        # Identify package-level exports that may have been defined for a custom ArgumentParser subclass
        modules = [module]
        while (parent := module.rsplit('.', 1)[0]) != module:
            if name in vars(sys.modules[parent]):
                modules.append(parent)
            module = parent

        for module in modules:
            log.debug(f'Registering {module}.{name} -> {ast_cls}')
            cls._parser_classes.setdefault(module, {})[name] = ast_cls

    @classmethod
    def register_parser(cls, ast_cls: ParserCls):
        cls._register_parser(ast_cls.represents, ast_cls)
        return ast_cls

    def add_parser(self, ast_cls: ParserCls, node: InitNode, call: OptCall, tracked_refs: TrackedRefMap) -> ParserObj:
        parser = ast_cls(node, self, tracked_refs, call)
        self._parsers.append(parser)
        return parser

    @cached_property
    def parsers(self) -> list[ParserObj]:
        from .visitor import ScriptVisitor, TrackedRef

        visitor = ScriptVisitor(self)
        visitor.track_refs_to(TrackedRef('argparse.REMAINDER'))
        visitor.track_refs_to(TrackedRef('argparse.SUPPRESS'))
        visitor.visit(self.root_node)
        return self._parsers


# region Decorators & Descriptors


class visit_func:
    """A method that can be called by an AST visitor."""
    __slots__ = ('func',)

    def __init__(self, func):
        self.func = func

    def __set_name__(self, owner: Type[AstCallable], name: str):
        owner._add_visit_func(name)
        setattr(owner, name, self.func)  # There's no need to keep the descriptor - replace self with func

    def __get__(self, instance, owner):
        # This will never actually be called, but it makes PyCharm happy
        return self if instance is None else partial(self.func, instance)


class AddVisitedChild(Generic[AC]):
    """Simplifies the definition of an add_child method that can be called by an AST visitor, where possible."""
    __slots__ = ('child_cls', 'list_attr')

    def __init__(self, child_cls: Type[AC], attr: str):
        self.child_cls = child_cls
        self.list_attr = attr

    def __set_name__(self, owner: Type[ArgCollection], name: str):
        owner._add_visit_func(name)

    def __get__(self, instance: ArgCollection, owner) -> Callable[[InitNode, Call, TrackedRefMap], AC]:
        if instance is None:
            return self  # noqa
        return partial(instance._add_child, self.child_cls, getattr(instance, self.list_attr))  # noqa


# endregion


class AstCallable:
    represents: RepresentedCallable
    visit_funcs = set()
    _sig: Signature | None = None

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

    def __init_subclass__(cls, represents: RepresentedCallable = None, **kwargs):
        super().__init_subclass__(**kwargs)
        if represents:
            cls.represents = represents
            cls._sig = None

    def __init__(self, node: InitNode, parent: AstCallable | Script, tracked_refs: TrackedRefMap, call: Call = None):
        self.init_node = node
        if not call:
            call = node.value if isinstance(node, Assign) else node  # type: Call
        self.call_node = call
        self.call_args = call.args
        self.call_kwargs = call.keywords
        self._tracked_refs = tracked_refs
        self.parent = parent
        self.names = set()

    def __repr__(self) -> str:
        return f'<{self.__class__.__name__}[{self.init_call_repr()}]>'

    def get_tracked_refs(self, module: str, name: str, default: D = _NotSet) -> set[str] | D:
        for tracked_ref, refs in self._tracked_refs.items():
            if tracked_ref.module == module and tracked_ref.name == name:
                return refs
        if default is not _NotSet:
            return default
        raise KeyError(f'No tracked ref found for {module}.{name}')

    # region Initialization Call

    @classmethod
    def _signature(cls) -> Signature:
        if not (sig := cls._sig):
            cls._sig = sig = Signature.from_callable(cls.represents)
        return sig

    @property
    def signature(self) -> Signature:
        return self._signature()

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
        except (TypeError, AttributeError):  # No represents func
            args = self.call_args
        return [ast.unparse(arg) for arg in args]

    def _init_func_kwargs(self) -> dict[str, str]:
        try:
            kwargs = self._init_func_bound.arguments
        except (TypeError, AttributeError):  # No represents func
            kwargs = {kw.arg: kw.value for kw in self.call_kwargs}
        else:
            kwargs = kwargs.copy()
            kwargs.pop('self', None)
            if isinstance(kwargs.get('args'), tuple):
                kwargs.pop('args')
            if isinstance(kwargs.get('kwargs'), dict):
                kwargs.update(kwargs.pop('kwargs'))
        return {key: ast.unparse(val) for key, val in kwargs.items()}

    @cached_property
    def init_func_kwargs(self) -> dict[str, str]:
        return self._init_func_kwargs()

    def init_call_repr(self) -> str:
        arg_str = ', '.join(self.init_func_args)
        if kw_str := ', '.join(f'{k}={v}' for k, v in self.init_func_kwargs.items()):
            arg_str = kw_str if not arg_str else (arg_str + ', ' + kw_str)
        return f'{self.init_func_name}({arg_str})'

    # endregion

    def walk_nodes(self) -> Iterator[AST]:
        yield self.init_node

    def pprint(self, indent: int = 0):
        print(f'{" " * indent} - {self!r}')


# region Stdlib Argparse Wrappers


class ParserArg(AstCallable, represents=ArgumentParser.add_argument):
    parent: ArgCollection


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

    def __init__(self, node: InitNode, parent: AstCallable | Script, tracked_refs: TrackedRefMap, call: Call = None):
        super().__init__(node, parent, tracked_refs, call)
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

    def _add_child(self, cls: Type[AC], container: list[AC], node: InitNode, call: Call, refs: TrackedRefMap) -> AC:
        child = cls(node, self, refs, call)
        container.append(child)
        return child

    @visit_func
    def add_mutually_exclusive_group(self, node: InitNode, call: Call, tracked_refs: TrackedRefMap):
        return self._add_child(MutuallyExclusiveGroup, self.groups, node, call, tracked_refs)

    @visit_func
    def add_argument_group(self, node: InitNode, call: Call, tracked_refs: TrackedRefMap):
        return self._add_child(ArgGroup, self.groups, node, call, tracked_refs)

    def grouped_children(self) -> Iterator[list[AC]]:
        yield self.args
        yield self.groups

    def walk_nodes(self) -> Iterator[AST]:
        yield from super().walk_nodes()
        for child_group in self.grouped_children():
            for child in child_group:
                yield from child.walk_nodes()

    # region Output Methods

    def pprint(self, indent: int = 0):
        print(f'{" " * indent} + {self!r}:')
        indent += 3
        for attr in self._children:
            if values := getattr(self, attr):
                for value in values:
                    value.pprint(indent)

    # endregion


class ArgGroup(ArgCollection, represents=_ArgumentParser.add_argument_group):
    pass


class MutuallyExclusiveGroup(ArgGroup, represents=_ArgumentParser.add_mutually_exclusive_group):
    pass


class SubparsersAction(AstCallable, represents=_ArgumentParser.add_subparsers):
    parent: ParserObj

    @visit_func
    def add_parser(self, node: InitNode, call: Call, tracked_refs: TrackedRefMap):
        sub_parser = self.parent._add_subparser(node, call, tracked_refs)
        sub_parser.sp_parent = self
        return sub_parser


@Script.register_parser
class AstArgumentParser(ArgCollection, represents=ArgumentParser, children=('sub_parsers',)):
    is_stdlib: bool = True
    sub_parsers: list[SubParser]
    add_subparsers = AddVisitedChild(SubparsersAction, '_subparsers_actions')

    def __init_subclass__(cls, is_stdlib: bool = False, **kwargs):
        super().__init_subclass__(**kwargs)
        cls.is_stdlib = is_stdlib

    def __init__(self, node: InitNode, parent: AstCallable | Script, tracked_refs: TrackedRefMap, call: Call = None):
        super().__init__(node, parent, tracked_refs, call)
        self._subparsers_actions = []
        # Note: sub_parsers aren't included in grouped_children since they need different handling during conversion
        self.sub_parsers = []

    def __repr__(self) -> str:
        stdlib, sub_parsers = self.is_stdlib, len(self.sub_parsers)
        assign_repr = f'``{" = ".join(sorted(self.names))} = {self.init_call_repr()}``'
        return f'<{self.__class__.__name__}[{stdlib=}, {sub_parsers=}]: {assign_repr}>'

    def _add_subparser(self, node: InitNode, call: Call, tracked_refs: TrackedRefMap, sub_parser_cls: ParserCls = None):
        # Using default of None since the class hasn't been defined at the time it would need to be set as default
        return self._add_child(sub_parser_cls or SubParser, self.sub_parsers, node, call, tracked_refs)

    def walk_nodes(self) -> Iterator[AST]:
        yield from super().walk_nodes()
        for sub_parser in self.sub_parsers:
            yield from sub_parser.walk_nodes()


class SubParser(AstArgumentParser, represents=_SubParsersAction.add_parser, is_stdlib=True):
    sp_parent: SubparsersAction = None

    @cached_property
    def init_func_kwargs(self) -> dict[str, str]:
        if sp_parent := self.sp_parent:
            return sp_parent.init_func_kwargs | self._init_func_kwargs()
        return self._init_func_kwargs()


# endregion
