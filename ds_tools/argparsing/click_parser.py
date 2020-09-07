"""
Utilities for making Click easier to work with

:author: Doug Skrypa
"""

import sys
from functools import wraps
from pathlib import Path
from typing import Iterable

from click.core import augment_usage_errors, Group, Option
from click.decorators import _param_memo
from click.exceptions import UsageError
from click.globals import get_current_context

__all__ = ['CommonArgs', 'CommonOption', 'MutuallyExclusiveOption']


class CommonArgs:
    __instance = None

    def __new__(cls, *args, **kwargs):
        if cls.__instance is None:
            cls.__instance = super().__new__(cls)
            cls.__instance.__initialized = False
        return cls.__instance

    def __init__(self, **defaults):
        if not self.__initialized:
            # fmt: off
            self.__initialized = True
            self._options = {
                'verbose': CommonOption(
                    ('--verbose', '-v'), count=True, default=defaults.get('verbose', 0),
                    help='Increase logging verbosity (can specify multiple times)',
                ),
                'dry_run': CommonOption(
                    ('--dry_run', '-D'), is_flag=True, enabled=False,
                    help='Print the actions that would be taken instead of taking them',
                ),
                'extra_cols': CommonOption(
                    ('--extra', '-e'), count=True, default=0, enabled=False,
                    help='Increase the number of columns displayed (can specify multiple times)',
                ),
                'select': CommonOption(
                    ('--select', '-s'), enabled=False, help='Nested key to select, using JQ-like syntax'
                ),
                'parallel': CommonOption(
                    ('--parallel', '-P'), type=int, default=1, enabled=False,
                    help='Maximum number of workers to use in parallel (default: %(default)s)',
                ),
                'yes': CommonOption('--yes', '-y', is_flag=True, enabled=False, help='Confirm all Yes/No prompts'),
            }
            # fmt: on

    def __repr__(self):
        return f'<{self.__class__.__name__}[{self.verbose=}, {self.dry_run=}]>'

    def __getattr__(self, item):
        try:
            return self[item]
        except KeyError:
            raise AttributeError(item)

    def __getitem__(self, item):
        return self._options[item].value

    def __setitem__(self, key, value):
        self._options[key].value = value

    @classmethod
    def enable(cls, **options):
        """Set the default enabled state for subsequent functions with Click parsers"""
        self = cls()
        for key, value in options.items():
            self._options[key].enabled = value
        return lambda func: func

    @classmethod
    def defaults(cls, **options):
        self = cls()
        for key, value in options.items():
            self._options[key].value = value
        return lambda func: func

    @classmethod
    def add_option(cls, *args, **kwargs):
        option = CommonOption(args, **kwargs)
        cls()._options[option.name] = option
        return lambda func: func

    @classmethod
    def common(cls, **enable):
        def decorator(func):
            self = cls()
            for key, option in sorted(self._options.items()):
                if enable.get(key, option.enabled):
                    _param_memo(func, option)

            @wraps(func)
            def wrapper(*args, **kwargs):
                ctx = get_current_context()
                ctx.ensure_object(cls)
                return func(*args, **kwargs)
            return wrapper
        return decorator

    @staticmethod
    def process_common_args(args=(), prog=None):
        """Traverse all subcommands and execute their parsers to update common options"""
        prog, args = prog or Path(sys.argv[0]).name, args or sys.argv[1:]
        ctx = get_current_context()
        cmd = ctx.command
        while isinstance(cmd, Group):
            name, cmd, args = cmd.resolve_command(ctx, args)
            ctx = cmd.make_context(prog, args, ctx)
            # Not done for the full top-level args because it will have already been done by the point this is called:
            cmd.parse_args(ctx, args)


class CommonOption(Option):
    def __init__(self, *args, enabled=True, **kwargs):
        super().__init__(*args, **kwargs)
        self.enabled = enabled
        self.value = self.default

    def handle_parse_result(self, ctx, opts, args):
        with augment_usage_errors(ctx, param=self):
            value = self.consume_value(ctx, opts)
            try:
                value = self.full_process_value(ctx, value)
            except Exception:
                if not ctx.resilient_parsing:
                    raise
                value = None

            if value != self.default:
                self.value = value

        return value, args


class MutuallyExclusiveOption(Option):
    def __init__(self, *args, conflicts: Iterable[str], **kwargs):
        super().__init__(*args, **kwargs)
        self.conflicts = set(conflicts)

    def handle_parse_result(self, ctx, opts, args):
        if self.name in opts and (conflicts := self.conflicts.intersection(opts)):
            # noinspection PyUnboundLocalVariable
            raise UsageError(f'Argument {self.name} is not allowed with arguments {conflicts}', ctx)
        return super().handle_parse_result(ctx, opts, args)
