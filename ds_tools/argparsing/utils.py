"""
Utilities for argparse

:author: Doug Skrypa
"""

from itertools import chain

__all__ = ['add_subparser_default_if_missing']


class Arg:
    """Only used to store positional & keyword args for common args so alternate default values can be provided"""
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs

    def __repr__(self):
        args = (repr(val) for val in self.args)
        kwargs = ('{}={}'.format(k, v.__name__ if k == 'type' else repr(v)) for k, v in self.kwargs.items())
        return '<{}({})>'.format(type(self).__name__, ','.join(chain(args, kwargs)))

    __str__ = __repr__


COMMON_ARGS = {
    'verbosity': ('add_common_arg', Arg('--verbose', '-v', action='count', help='Increase logging verbosity (can specify multiple times)')),
    'extra_cols': ('add_common_sp_arg', Arg('--extra', '-e', action='count', default=0, help='Increase the number of columns displayed (can specify multiple times)')),
    'select': ('add_common_sp_arg', Arg('--select', '-s', help='Nested key to select, using JQ-like syntax')),
    'parallel': ('add_common_sp_arg', Arg('--parallel', '-P', type=int, default=1, help='Maximum number of workers to use in parallel (default: %(default)s)')),
    'dry_run': ('add_common_sp_arg', Arg('--dry_run', '-D', action='store_true', help='Print the actions that would be taken instead of taking them')),
    'yes': ('add_common_sp_arg', Arg('--yes', '-y', action='store_true', help='Confirm all Yes/No prompts')),
}   #: Common argparse arguments; defining them this way increases consistency between scripts


def update_subparser_constants(parser, parsed):
    for dest, subparsers in parser.subparsers.items():
        chosen_sp = parsed.__dict__[dest]
        for sp_name, subparser in subparsers.choices.items():
            if sp_name == chosen_sp:
                parsed.__dict__.update(subparser._ArgParser__constants)
                update_subparser_constants(subparser, parsed)


def add_subparser_default_if_missing(args, subparsers, default_value, start_index=1):
    i = (start_index + 1) if start_index > -2 else 0
    found_sp_key = False
    for arg in args[i:]:
        if arg in subparsers.choices.keys():
            found_sp_key = True
            break
    if not found_sp_key:
        args.insert(i, default_value)
    return args
