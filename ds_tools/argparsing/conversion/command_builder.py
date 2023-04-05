from __future__ import annotations

import keyword
import logging
from abc import ABC, abstractmethod
from ast import literal_eval
from dataclasses import dataclass, fields
from itertools import count
from typing import TYPE_CHECKING, Iterator, Iterable, Type

from cli_command_parser.nargs import Nargs

from ds_tools.caching.decorators import cached_property
from .argparse_ast import AC, ParserArg, ArgGroup, MutuallyExclusiveGroup, AstArgumentParser, Script

if TYPE_CHECKING:
    from .argparse_ast import ArgCollection

__all__ = ['convert_script']
log = logging.getLogger(__name__)

OptStr = str | None
RESERVED = set(keyword.kwlist) | set(keyword.softkwlist)


def convert_script(script: Script) -> str:
    return ScriptConverter(script).convert()


class Converter(ABC):
    converts: Type[AC] = None
    _ac_converter_map = {}

    def __init_subclass__(cls, converts: Type[AC] = None, **kwargs):
        super().__init_subclass__(**kwargs)
        if converts:
            cls.converts = converts
            cls._ac_converter_map[converts] = cls

    def __init__(self, ast_obj: AC | Script):
        self.ast_obj = ast_obj

    @classmethod
    def for_ast_callable(cls, ast_obj: AC) -> Converter:
        if converter_cls := cls._ac_converter_map.get(ast_obj.__class__):
            return converter_cls
        for converts_cls, converter_cls in cls._ac_converter_map.items():
            if isinstance(ast_obj, converts_cls):
                return converter_cls
        raise TypeError(f'No Converter is registered for {ast_obj.__class__.__name__} objects')

    @classmethod
    def format_all(cls, parent: Converter, ast_objs: list[AC], indent: int = 0) -> Iterator[str]:
        for ast_obj in ast_objs:
            yield from cls(ast_obj).format_lines(indent)

    def convert(self, indent: int = 0) -> str:
        return '\n'.join(self.format_lines(indent))

    @abstractmethod
    def format_lines(self, indent: int = 0) -> Iterator[str]:
        raise NotImplementedError


class ScriptConverter(Converter, converts=Script):
    def format_lines(self, indent: int = 0) -> Iterator[str]:
        # TODO: Filter to what is actually used
        yield (
            'from cli_command_parser import'
            ' Command, SubCommand, ParamGroup, Positional, Option, Flag, Counter, PassThru, main'
        )
        yield ''
        for parser in self.ast_obj.parsers:
            yield from ParserConverter(parser).format_lines()


class CollectionConverter(Converter, ABC):
    ast_cls: ArgCollection

    def format_members(self, prefix: str, indent: int = 4) -> Iterator[str]:
        had_members = False
        for child_group in self.ast_obj.grouped_children():
            if child_group:
                had_members = True
                yield from self.for_ast_callable(child_group[0]).format_all(self, child_group, indent)

        if not had_members:
            yield f'{prefix}    pass'


class ParserConverter(CollectionConverter, converts=AstArgumentParser):
    _auto_gen_disclaimer = '# This is an automatically generated name that should probably be updated'
    ast_obj: AstArgumentParser

    def __init__(self, parser: AstArgumentParser, parent: str = 'Command', counter: count = None):
        super().__init__(parser)
        self.parent = parent
        self.counter = count() if counter is None else counter

    def format_lines(self, indent: int = 0) -> Iterator[str]:
        suffix = f'  {self._auto_gen_disclaimer}' if self.parent == 'Command' else ''
        name = f'Command{next(self.counter)}'
        yield '\n'
        yield f'class {name}({self.parent}{self._get_args()}):{suffix}'
        yield from self.format_members('')
        for sub_parser in self.ast_obj.sub_parsers:
            yield from self.__class__(sub_parser, name, self.counter).format_lines()

    def _get_args(self) -> str:
        # TODO: Finish this
        parser = self.ast_obj
        # log.debug(f'Processing args for {parser._init_func_bound}')
        sp_parent = getattr(parser, 'sp_parent', None)
        is_sub_parser = isinstance(parser.parent, AstArgumentParser)

        return ''


class GroupConverter(CollectionConverter, converts=ArgGroup):
    ast_obj: ArgGroup

    def format_lines(self, indent: int = 4) -> Iterator[str]:
        prefix = ' ' * indent
        yield f'\n{prefix}with ParamGroup({self._get_args()}):'
        yield from self.format_members(prefix, indent + 4)

    def _get_args(self) -> str:
        # log.debug(f'Processing args for {self.ast_obj._init_func_bound}')
        description = self.ast_obj.init_func_kwargs.get('description')
        if title := self.ast_obj.init_func_kwargs.get('title'):
            title_str = literal_eval(title)
            if title_str.lower().endswith(' options'):
                if description:
                    title = repr(title_str[:-7].rstrip())
                else:
                    description, title = title, None

        args = [title] if title else []
        if description:
            args.append(f'description={description}')
        if isinstance(self.ast_obj, MutuallyExclusiveGroup):
            args.append('mutually_exclusive=True')
        return ', '.join(args)


class ParamConverter(Converter, converts=ParserArg):
    ast_obj: ParserArg
    _counter = count()

    def __init__(self, arg: ParserArg, num: int):
        super().__init__(arg)
        self.num = num

    def __eq__(self, other: ParamConverter) -> bool:
        return self.ast_obj == other.ast_obj and self.num == other.num

    def __lt__(self, other: ParamConverter) -> bool:
        if self.is_positional and not other.is_positional:
            return True
        if self.is_pass_thru and not other.is_pass_thru:
            return False
        return self.num < other.num

    @classmethod
    def format_all(cls, parent: CollectionConverter, args: list[ParserArg], indent: int = 4) -> Iterator[str]:
        positionals, others = [], []
        i_converters = iter(sorted(cls(arg, i) for i, arg in enumerate(args)))
        for converter in i_converters:
            if converter.is_positional:
                positionals.append(converter)
            else:
                others.append(converter)
                others.extend(i_converters)

        for positional in positionals:
            yield from positional.format_lines(indent)

        if sub_parsers := getattr(parent.ast_obj, 'sub_parsers', None):
            try:
                name = literal_eval(sub_parsers[0].init_func_kwargs['dest']).replace('-', '_')
            except (KeyError, ValueError):
                name = 'sub_cmd'
            else:
                if name in RESERVED:
                    name = 'sub_cmd'
            yield f'{" " * indent}{name} = SubCommand()'

        for other in others:
            yield from other.format_lines(indent)

    def format_lines(self, indent: int = 4) -> Iterator[str]:
        yield self.format(indent)

    def format(self, indent: int = 4) -> str:
        param_cls, args_obj = self.get_cls_and_kwargs()
        arg_str = ', '.join((*self.get_pos_args(), args_obj.to_str()))
        return f'{" " * indent}{self.attr_name} = {param_cls}({arg_str})'

    # region Naming

    @cached_property
    def attr_name(self) -> str:
        name_candidates = self._attr_name_candidates()
        while name := next(name_candidates):
            if name not in RESERVED:
                return name

    def _attr_name_candidates(self) -> Iterator[str]:
        long, short, plain = self._grouped_opt_strs
        if self.is_positional or self.is_pass_thru:
            for value in plain:
                yield value.replace('-', '_')
        if self.is_option or self.is_pass_thru:
            for group in (long, short):
                for opt in group:
                    if opt := opt.lstrip('-'):
                        yield opt.replace('-', '_')
        while True:
            yield f'param_{next(self._counter)}'

    # endregion

    # region Arg Processing

    def get_pos_args(self) -> Iterable[str]:
        if not self.is_option:
            return ()
        long, short, plain = self._grouped_opt_strs
        if skip_long := len(long) == 1:
            skip_long &= long[0][2:] in (self.attr_name, self.attr_name.replace('_', '-'))
        args = short if skip_long else (long + short)
        return (repr(arg) for arg in args)

    def get_cls_and_kwargs(self) -> tuple[str, BaseArgs]:
        kwargs = self.ast_obj.init_func_kwargs.copy()
        if (help_arg := kwargs.get('help')) and help_arg in self.ast_obj.get_tracked_refs('argparse', 'SUPPRESS', ()):
            kwargs |= {'hide': 'True', 'help': None}

        if self.is_pass_thru:
            return 'PassThru', PassThruArgs.from_kwargs(**kwargs)

        if action := kwargs.pop('action', None):
            action = literal_eval(action)

        if self.is_positional:
            if action and action not in ('store', 'append'):
                raise ConversionError(f'{self.ast_obj}: {action=} is not supported for Positional parameters')
            return 'Positional', ParamArgs.init_positional(action, **kwargs)
        elif self.is_option:
            if action:
                if action in ('store_true', 'store_false', 'store_const', 'append_const'):
                    return 'Flag', FlagArgs.init_flag(action, **kwargs)
                elif action == 'count':
                    return 'Counter', FlagArgs.init_counter(**kwargs)
                elif action not in ('store', 'append'):
                    raise ConversionError(f'{self.ast_obj}: {action=} is not supported for Option parameters')
            return 'Option', ParamArgs.init_option(self.ast_obj, action, **kwargs)

        raise ConversionError(f'Unable to determine a suitable Parameter type for {self.ast_obj!r}')

    # endregion

    # region High Level Param Type

    @cached_property
    def is_pass_thru(self) -> bool:
        if not (nargs := self.ast_obj.init_func_kwargs.get('nargs')):
            return False
        return nargs in self.ast_obj.get_tracked_refs('argparse', 'REMAINDER', ())

    @cached_property
    def is_positional(self) -> bool:
        long, short, plain = self._grouped_opt_strs
        return plain and not long and not short

    @cached_property
    def is_option(self) -> bool:
        long, short, plain = self._grouped_opt_strs
        return (long or short) and not plain

    # endregion

    @cached_property
    def _grouped_opt_strs(self) -> tuple[list[str], list[str], list[str]]:
        option_strs = (literal_eval(opt) for opt in self.ast_obj.init_func_args)
        long, short, plain = [], [], []
        for opt in option_strs:
            if opt.startswith('--'):
                long.append(opt)
            elif opt.startswith('-'):
                short.append(opt)
            else:
                plain.append(opt)
        return long, short, plain


# region ParserArg Arg Containers


@dataclass
class BaseArgs:
    name: OptStr = None
    default: OptStr = None
    required: OptStr = None
    metavar: OptStr = None
    help: OptStr = None
    hide: OptStr = None

    def to_str(self) -> str:
        skip = {'hide', 'help'}
        keys = [f.name for f in fields(self) if f.name not in skip] + ['hide', 'help']
        return ', '.join(f'{key}={val}' for key in keys if (val := getattr(self, key)) is not None)

    @classmethod
    def from_kwargs(cls, **kwargs):
        keys = set(f.name for f in fields(cls)).intersection(kwargs)
        filtered = {key: kwargs[key] for key in keys}
        if help_str := filtered.get('help'):
            # log.debug(f'Processing {help_str=}')
            try:
                help_str = literal_eval(help_str)
            except ValueError:  # likely an f-string
                pass
            else:
                if help_str.endswith('(default: %(default)s)'):
                    help_str = help_str[:-22].rstrip()
                filtered['help'] = repr(help_str) if help_str else None

        return cls(**filtered)


@dataclass
class PassThruArgs(BaseArgs):
    pass


@dataclass
class ParamArgs(BaseArgs):
    action: OptStr = None
    type: OptStr = None
    nargs: OptStr = None
    choices: OptStr = None

    @classmethod
    def init_positional(cls, action: OptStr = None, nargs: OptStr = None, **kwargs):
        if nargs is not None:
            nargs_obj = Nargs(literal_eval(nargs))
        else:
            nargs_obj = Nargs(1)
        if (action == 'store' and nargs_obj == 1) or (action == 'append' and nargs_obj != Nargs(1)):
            action = None
        return cls.from_kwargs(action=action, nargs=nargs, **kwargs)

    @classmethod
    def init_option(cls, arg: ParserArg, action: OptStr = None, nargs: OptStr = None, const: OptStr = None, **kwargs):
        if const:
            log.warning(f'{arg}: ignoring {const=} - it is only supported for Flag and Counter parameters')

        if action == 'append':
            if not nargs:
                log.debug(f"{arg}: using default nargs='+' because {action=} and no nargs value was provided")
                nargs = "'+'"
            action = None
        elif action == 'store':
            if nargs == '1':
                nargs = None
            if not nargs:
                action = None

        return cls.from_kwargs(action=repr(action) if action else None, nargs=nargs, **kwargs)


@dataclass
class FlagArgs(ParamArgs):
    const: OptStr = None

    @classmethod
    def init_flag(cls, action: str, const: OptStr = None, default: OptStr = None, **kwargs):
        values = {'store_true': ('True', 'False'), 'store_false': ('False', 'True')}
        try:
            value, opposite = values[action]
        except KeyError:
            if action == 'store_const':
                action = None
        else:
            if default == opposite:
                default = None
            action = None
            const = value if default else None

        kwargs['type'] = kwargs['nargs'] = None
        if action:
            action = repr(action)
        return cls.from_kwargs(action=action, const=const, default=default, **kwargs)

    @classmethod
    def init_counter(cls, const: OptStr = None, default: OptStr = None, **kwargs):
        kwargs['type'] = kwargs['nargs'] = kwargs['action'] = None
        kwargs['const'] = None if const == '1' else const
        kwargs['default'] = None if default == '0' else default
        return cls.from_kwargs(**kwargs)


# endregion


class ConversionError(Exception):
    pass
