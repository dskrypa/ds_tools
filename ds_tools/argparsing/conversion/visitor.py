from __future__ import annotations

import logging
from ast import NodeVisitor, AST, Assign, Call, For, Attribute, Name
from collections import ChainMap, defaultdict
from functools import partial, wraps

from .ast_utils import get_name_repr, imp_names
from .argparse_ast import Script, AstArgumentParser

__all__ = ['ScriptVisitor', 'TrackedRef']
log = logging.getLogger(__name__)

TrackedRefMap = dict['TrackedRef', set[str]]
_NoCall = object()


def scoped(func):
    @wraps(func)
    def _scoped_method(self: ScriptVisitor, *args, **kwargs):
        self.scopes = self.scopes.new_child()
        try:
            func(self, *args, **kwargs)
        finally:
            self.scopes = self.scopes.parents
    return _scoped_method


class ScopedVisit:
    __slots__ = ()

    def __get__(self, instance: ScriptVisitor, owner):
        return self if instance is None else partial(scoped(owner.generic_visit), instance)


class ScriptVisitor(NodeVisitor):
    visit_FunctionDef = visit_AsyncFunctionDef = ScopedVisit()
    visit_Lambda = ScopedVisit()
    visit_ClassDef = ScopedVisit()
    visit_While = ScopedVisit()

    def __init__(self, script: Script):
        self.script = script
        self.scopes = ChainMap()
        self._tracked_refs = set()
        self._import_tracked_ref_map = {}

    def track_refs_to(self, ref: TrackedRef):
        self._tracked_refs.add(ref)
        self._import_tracked_ref_map.setdefault(ref.module, {})[ref.name] = ref

    def get_tracked_refs(self) -> TrackedRefMap:
        tracked_refs = defaultdict(set)
        for key, val in self.scopes.items():
            if val in self._tracked_refs:
                tracked_refs[val].add(key)
        tracked_refs.default_factory = None
        return tracked_refs

    # region Imports

    def visit_Import(self, node):
        for module_name, as_name in imp_names(node):
            # TODO: Unify _import_tracked_ref_map and mod_cls_to_ast_cls_map
            if name_tr_map := self._import_tracked_ref_map.get(module_name):
                for name, tracked_ref in name_tr_map.items():
                    self.scopes[f'{as_name}.{name}'] = tracked_ref

            if name_ast_map := self.script.mod_cls_to_ast_cls_map.get(module_name):
                log.debug(f'Found module import: {module_name} as {as_name}')
                for cls_name, ast_cls in name_ast_map.items():
                    self.scopes[f'{as_name}.{cls_name}'] = partial(self.script.add_parser, ast_cls)

    def visit_ImportFrom(self, node):
        if name_tr_map := self._import_tracked_ref_map.get(node.module):
            for name, as_name in imp_names(node):
                if tracked_ref := name_tr_map.get(name):
                    self.scopes[as_name] = tracked_ref

        if name_ast_map := self.script.mod_cls_to_ast_cls_map.get(node.module):
            for name, as_name in imp_names(node):
                if ast_cls := name_ast_map.get(name):
                    log.debug(f'Found class import: {node.module}.{name} as {as_name}')
                    self.scopes[as_name] = partial(self.script.add_parser, ast_cls)

    # endregion

    # region Scope Changes

    @scoped
    def visit_For(self, node: For):
        if isinstance(node.target, Name):
            try:
                ele_names = [get_name_repr(ele) for ele in node.iter.elts]  # noqa
            except (AttributeError, TypeError):
                ele_names = ()

            if ele_names and self.script.smart_loop_handling:
                self._visit_for_smart(node, node.target.id, ele_names)
            else:
                self._visit_for_elements(node, node.target.id, ele_names)
        else:
            self.generic_visit(node)

    visit_AsyncFor = visit_For

    def _visit_for_smart(self, node: For, loop_var: str, ele_names: list[str]):
        log.debug(f'Attempting smart for loop visit for {loop_var=} in {ele_names=}')
        refs = [ref for name in ele_names if (ref := self.scopes.get(name))]
        log.debug(f'  > Found {len(refs)=}, {len(ele_names)=}')

        if len(refs) == len(ele_names) and all(isinstance(ref, AstArgumentParser) for ref in refs):
            parents = set(ref.parent for ref in refs)
            log.debug(f'  > Found {parents=}')
            if len(parents) == 1 and (parent := next(iter(parents))) and set(parent.sub_parsers) == set(refs):  # noqa
                self.scopes[loop_var] = parent
                self.generic_visit(node)
                return

        log.debug(f'Falling back to generic loop handling')
        self._visit_for_elements(node, loop_var, ele_names)

    def _visit_for_elements(self, node: For, loop_var: str, ele_names: list[str]):
        visited_any = False
        for name in ele_names:
            if ref := self.scopes.get(name):
                visited_any = True
                self.scopes[loop_var] = ref
                self.generic_visit(node)

        if not visited_any:
            self.generic_visit(node)

    # endregion

    def resolve_ref(self, name: str | AST):
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
        if func := self.resolve_ref(context_expr):
            call = context_expr if isinstance(context_expr, Call) else None
            result = func(item, call, self.get_tracked_refs())
            if as_name := item.optional_vars:
                self.scopes[get_name_repr(as_name)] = result

    def visit_Assign(self, node: Assign):
        value = node.value
        if isinstance(value, (Attribute, Name)):  # Assigning an alias to a variable
            if ref := self.resolve_ref(value):
                for target in node.targets:
                    self.scopes[get_name_repr(target)] = ref
        elif isinstance(value, Call):
            if (result := self.visit_Call(value)) is not _NoCall:
                for target in node.targets:
                    self.scopes[get_name_repr(target)] = result

    def visit_Call(self, node: Call):
        if func := self.resolve_ref(node.func):
            return func(node, node, self.get_tracked_refs())
        return _NoCall


class TrackedRef:
    __slots__ = ('module', 'name')

    def __init__(self, name: str):
        self.module, self.name = name.rsplit('.', 1)

    def __repr__(self) -> str:
        return f'<{self.__class__.__name__}: {self.module}.{self.name}>'

    def __hash__(self) -> int:
        return hash(self.__class__) ^ hash(self.module) ^ hash(self.name)

    def __eq__(self, other: TrackedRef) -> bool:
        return self.name == other.name and self.module == other.module
