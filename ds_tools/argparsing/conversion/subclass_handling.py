from __future__ import annotations

import logging
from ast import AST, Call, Attribute, Name, Constant, Load, keyword, literal_eval
from typing import TYPE_CHECKING, Iterator

from ds_tools.argparsing.argparser import ArgParser
from ds_tools.argparsing.utils import COMMON_ARGS
from .argparse_ast import AstCallable, AstArgumentParser, Script, AddVisitedChild, ParserArg, visit_func
from .ast_utils import get_name_repr
from .command_builder import Converter

if TYPE_CHECKING:
    from .argparse_ast import InitNode, SubParser, AC
    from .visitor import TrackedRefMap

__all__ = ['ParserConstant', 'AstArgParser', 'SubParserShortcut', 'ConstantConverter']
log = logging.getLogger(__name__)


class ParserConstant(AstCallable, represents=ArgParser.add_constant):
    parent: AstArgParser


@Script.register_parser
class AstArgParser(AstArgumentParser, represents=ArgParser, children=('constants',)):
    sub_parsers: list[SubParser | SubParserShortcut]
    constants: list[ParserConstant]
    add_constant = AddVisitedChild(ParserConstant, 'constants')
    # Note: Skipping addition to each subparser for add_common*arg methods to take advantage of Command inheritance
    add_common_sp_arg = AddVisitedChild(ParserArg, 'args')
    add_common_arg = AddVisitedChild(ParserArg, 'args')

    def __init__(self, node: InitNode, parent: AstCallable | Script, tracked_refs: TrackedRefMap, call: Call = None):
        super().__init__(node, parent, tracked_refs, call)
        self.constants = []

    @visit_func
    def add_subparser(self, node: InitNode, call: Call, tracked_refs: TrackedRefMap):
        return self._add_subparser(node, call, tracked_refs, SubParserShortcut)

    @visit_func
    def include_common_args(self, node: InitNode, call: Call, tracked_refs: TrackedRefMap):
        kwargs = {a.value: None for a in node.args if isinstance(a, Constant)} | {k.arg: k.value for k in node.keywords}
        common_args = []
        for key, val in kwargs.items():
            try:
                method, spec = COMMON_ARGS[key]
            except KeyError:
                log.debug(f'Unrecognized include_common_args key={key!r}')
            else:
                kvargs = (spec.kwargs | {'default': val}) if val is not None else spec.kwargs
                common_args.append((method, spec.args, kvargs))

        parser_name = get_name_repr(node.func).rsplit('.', 1)[0]
        for method, args, kwargs in common_args:
            try:
                add_arg_func = getattr(self, method)
            except AttributeError:
                log.warning(f'Method not implemented for {self.__class__.__name__}: {method!r}')
            else:
                fake_node = Call(
                    func=Attribute(Name(parser_name, Load()), attr=method, ctx=Load()),
                    args=[Constant(arg) for arg in args],
                    keywords=[keyword(k, _common_arg_val_to_ast(v)) for k, v in kwargs.items()],
                )
                add_arg_func(fake_node, fake_node, tracked_refs)

    def grouped_children(self) -> Iterator[list[AC]]:
        yield self.constants
        yield from super().grouped_children()


class SubParserShortcut(AstArgParser, represents=ArgParser.add_subparser):
    pass


def _common_arg_val_to_ast(value) -> AST:
    if isinstance(value, AST):
        return value
    elif isinstance(value, type):
        return Name(value.__name__, Load())
    else:
        return Constant(value)


class ConstantConverter(Converter, converts=ParserConstant):
    ast_obj: ParserConstant

    def format_lines(self, indent: int = 4) -> Iterator[str]:
        try:
            key, val = self.ast_obj.init_func_args
        except ValueError:
            log.debug(f'Unexpected add_constant args={self.ast_obj.init_func_args!r}')
        else:
            yield f'{" " * indent}{literal_eval(key)} = {val}'
