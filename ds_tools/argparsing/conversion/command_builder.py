from __future__ import annotations

import keyword
import logging
from ast import literal_eval
from itertools import count
from typing import Collection, Iterator, Any

from cli_command_parser.nargs import Nargs, NargsValue

from ds_tools.caching.decorators import cached_property
from .argparse_ast import ParserArg, ParserConstant, ArgGroup, MutuallyExclusiveGroup, ArgParser, Script

__all__ = ['convert_script']
log = logging.getLogger(__name__)

OptStr = str | None

RESERVED = set(keyword.kwlist) | set(keyword.softkwlist)


def convert_script(script: Script) -> str:
    return '\n'.join(_translate_script(script))


def _translate_script(script: Script) -> Iterator[str]:
    yield 'from cli_command_parser import Command, ParamGroup, Positional, Option, Flag, Counter, main'
    yield '\n'
    for parser in script.parsers:
        yield from _translate_parser(parser)


def _translate_parser(parser: ArgParser, parent: str = 'Command', cmd_counter: count = None) -> Iterator[str]:
    if cmd_counter is None:
        cmd_counter = count()

    name = f'Command{next(cmd_counter)}'
    yield f'class {name}({parent}):'  # TODO: command args

    if constants := parser.constants:
        yield from _translate_constants(constants)
    if args := parser.args:
        yield from _translate_args(args)
    if groups := parser.groups:
        for group in groups:
            yield from _translate_group(group)

    if not constants and not groups and not args:
        yield '    pass'

    yield '\n'

    if sub_parsers := parser.sub_parsers:
        for sub_parser in sub_parsers:
            yield from _translate_parser(sub_parser, name, cmd_counter)


def _translate_constants(constants: Collection[ParserConstant]) -> Iterator[str]:
    for constant in constants:
        try:
            key, val = constant.init_func_args
        except ValueError:
            log.debug(f'Unexpected add_constant args={constant.init_func_args!r}')
        else:
            yield f'    {key} = {val}'


def _translate_args(args: Collection[ParserArg], indent: int = 4) -> Iterator[str]:
    arg_count = 0
    for arg in args:
        arg_count += 1
        yield ParamTranslator(arg).format(indent)
    if arg_count:
        yield ''


def _translate_group(group: ArgGroup, indent: int = 4) -> Iterator[str]:
    prefix = ' ' * indent
    indent += 4
    arg_str = ''
    if isinstance(group, MutuallyExclusiveGroup):
        arg_str = 'mutually_exclusive=True'
    yield f'{prefix}with ParamGroup({arg_str}):'  # TODO: Handle other args

    had_members = False
    if group.args:
        had_members = True
        yield from _translate_args(group.args, indent)

    if group.groups:
        had_members = True
        for sub_group in group.groups:
            yield from _translate_group(sub_group, indent)

    if not had_members:
        yield f'{prefix}    pass'

    yield ''


class ParamTranslator:
    _counter = count()

    def __init__(self, arg: ParserArg):
        self.arg = arg

    def format(self, indent: int = 4) -> str:
        prefix = ' ' * indent
        new_args = self._get_pos_args()
        if self.is_positional:
            param_cls, new_kwargs = self._format_positional()
        elif self.is_option:
            param_cls, new_kwargs = self._format_option()
        else:
            raise ConversionError(f'Unable to determine a suitable Parameter type for {self.arg!r}')

        arg_str = ', '.join((*new_args, *(f'{k}={v}' for k, v in new_kwargs.items() if v is not None)))
        return f'{prefix}{self.attr_name} = {param_cls}({arg_str})'

    def _format_positional(self) -> tuple[str, dict[str, str]]:
        new_kwargs = {}
        nargs = self._maybe_add_nargs(new_kwargs, 1)
        if action := self.arg.init_func_kwargs.get('action'):
            if action not in ('store', 'append'):
                raise ConversionError(f'{self.arg}: {action=} is not supported for Positional parameters')
            elif not ((action == 'store' and nargs == 1) or (action == 'append' and nargs != Nargs(1))):
                new_kwargs['action'] = action

        self._maybe_add_type(new_kwargs)
        for key in ('metavar', 'choices', 'default', 'required'):
            self._maybe_add_kwarg(new_kwargs, key)

        self._maybe_add_help(new_kwargs)
        return 'Positional', new_kwargs

    def _format_option(self) -> tuple[str, dict[str, str]]:
        old_kwargs = self.arg.init_func_kwargs
        new_kwargs = {}
        param_cls = 'Option'

        log.debug(f'Processing option with {old_kwargs=}')

        const, default = old_kwargs.get('const'), old_kwargs.get('default')
        raw_nargs, arg_type = old_kwargs.get('nargs'), old_kwargs.get('type')
        if action := old_kwargs.get('action'):
            action = literal_eval(action)
            if action in ('store_true', 'store_false', 'store_const', 'append_const'):
                param_cls = 'Flag'
                arg_type = raw_nargs = None
                action, const, default = self._get_flag_args(action, const, default)
            elif action == 'count':
                param_cls = 'Counter'
                arg_type = raw_nargs = None
                if const == '1':
                    const = None
                if default == '0':
                    default = None
            elif action not in ('store', 'append'):
                raise ConversionError(f'{self.arg}: {action=} is not supported for Option parameters')
            elif action == 'append':
                if not raw_nargs:
                    raise ConversionError(
                        f'{self.arg}: {action=} is not supported without specifying a value for nargs'
                    )
                action = None
            elif action == 'store':
                if raw_nargs == '1':
                    raw_nargs = None
                if not raw_nargs:
                    action = None

        if const and param_cls not in ('Flag', 'Counter'):
            raise ConversionError(f'{self.arg}: {const=} is only supported for Flag and Counter parameters')

        new_kwargs |= {'action': action, 'type': arg_type, 'nargs': raw_nargs, 'const': const, 'default': default}
        keys = ('metavar', 'choices', 'required') if param_cls == 'Option' else ('required',)
        for key in keys:
            self._maybe_add_kwarg(new_kwargs, key)
        self._maybe_add_help(new_kwargs)
        return param_cls, new_kwargs

    def _get_flag_args(self, action: str, const: OptStr, default: OptStr) -> tuple[OptStr, OptStr, OptStr]:
        values = {'store_true': ('True', 'False'), 'store_false': ('False', 'True')}
        try:
            value, opposite = values[action]
        except KeyError:
            if action == 'store_const':
                action = None
            return action, const, default

        if default == opposite:
            default = None
        const = value if default else None
        return None, const, default

    def _get_pos_args(self) -> list[str]:
        if self.is_positional:
            return []

        long, short, plain = self._grouped_opt_strs
        include_long = not (len(long) == 1 and long[0] == f'--{self.attr_name}')
        args = (long + short) if include_long else short
        return [repr(arg) for arg in args]

    def _maybe_add_nargs(self, new_kwargs: dict[str, Any], default: NargsValue) -> Nargs:
        if (nargs := self.arg.init_func_kwargs.get('nargs')) is not None:
            new_kwargs['nargs'] = nargs
            return Nargs(literal_eval(nargs))
        else:
            return Nargs(default)

    def _maybe_add_type(self, new_kwargs: dict[str, Any]) -> str | None:
        if (arg_type := self.arg.init_func_kwargs.get('type')) not in (None, 'str'):
            new_kwargs['type'] = arg_type
        return arg_type

    def _maybe_add_kwarg(self, new_kwargs: dict[str, Any], key: str) -> str | None:
        if (value := self.arg.init_func_kwargs.get(key)) is not None:
            new_kwargs[key] = value
        return value

    def _maybe_add_help(self, new_kwargs: dict[str, Any]) -> str | None:
        if help_str := self.arg.init_func_kwargs.get('help'):
            if help_str.endswith('(default: %(default)s)'):
                help_str = help_str[:-22].rstrip()
            if help_str:
                new_kwargs['help'] = help_str
        return help_str

    @cached_property
    def _grouped_opt_strs(self) -> tuple[list[str], list[str], list[str]]:
        option_strs = (literal_eval(opt) for opt in self.arg.init_func_args)
        long, short, plain = [], [], []
        for opt in option_strs:
            if opt.startswith('--'):
                long.append(opt)
            elif opt.startswith('-'):
                short.append(opt)
            else:
                plain.append(opt)
        return long, short, plain

    @cached_property
    def is_positional(self) -> bool:
        long, short, plain = self._grouped_opt_strs
        return plain and not long and not short

    @cached_property
    def is_option(self) -> bool:
        long, short, plain = self._grouped_opt_strs
        return (long or short) and not plain

    def _attr_name_candidates(self) -> Iterator[str]:
        long, short, plain = self._grouped_opt_strs
        if self.is_positional:
            yield from plain
        elif self.is_option:
            for group in (long, short):
                for opt in group:
                    if opt := opt.lstrip('-'):
                        yield opt
        while True:
            yield f'param_{next(self._counter)}'

    @cached_property
    def attr_name(self) -> str:
        name_candidates = self._attr_name_candidates()
        while name := next(name_candidates):
            if name not in RESERVED:
                return name


class ConversionError(Exception):
    pass
