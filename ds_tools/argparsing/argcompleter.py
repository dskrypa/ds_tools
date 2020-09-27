"""
Extends the CompletionFinder from argcomplete to exclude other subparser actions when completing arguments for a
subparser.

:author: Doug Skrypa
"""

import os
import sys
from argparse import REMAINDER
from pathlib import Path

import argcomplete
from argcomplete import CompletionFinder

from .utils import iter_actions


class ArgCompletionFinder(CompletionFinder):
    def __call__(self, arg_parser, *args, ensure_comp_possible=True, **kwargs):
        if '_ARGCOMPLETE' not in os.environ:  # not an argument completion invocation
            return ensure_argcomplete_is_available(ensure_comp_possible)

        # argcomplete has the same behavior as argparse for REMAINDER args - it is very greedy and will supersede other
        # optional args
        for action in iter_actions(arg_parser):
            if action.nargs == REMAINDER:
                action.nargs = '*'

        return super().__call__(arg_parser, *args, **kwargs)

    # def _get_completions(self, comp_words, cword_prefix, cword_prequote, last_wordbreak_pos):
    #     ...
    #     # Patch: Filter out comp_words for already-processed positional args used to enter a subparser
    #     new_comp_words = []
    #     for word, pos in zip_longest(comp_words[1:], self.visited_positionals):
    #         if word and (not pos or word != pos.prog.split()[-1]):
    #             new_comp_words.append(word)
    #
    #     debug(f'{comp_words=} => {new_comp_words=}')


def ensure_argcomplete_is_available(ensure_comp_possible=True):
    if not ensure_comp_possible:
        return

    for path in ('~/.config/bash_completion.d/python-argcomplete', '~/.bash_completion.d/python-argcomplete'):
        if Path(path).expanduser().exists():
            return

    comp_dir = None
    for path in ('~/.config/bash_completion.d', '~/.bash_completion.d'):
        path = Path(path).expanduser()
        if path.is_dir():
            comp_dir = path
            break

    comp_dir = comp_dir or Path('~/.config/bash_completion.d').expanduser()
    if not comp_dir.exists():
        comp_dir.mkdir(parents=True)

    copy_bash_completion_script(comp_dir)


def copy_bash_completion_script(comp_dir: Path):
    comp_src = Path(argcomplete.__file__).resolve().parent.joinpath('bash_completion.d', 'python-argcomplete')
    if not comp_src.exists():
        return

    comp_path = comp_dir.joinpath('python-argcomplete')
    print('=' * 100, file=sys.stderr)
    print(f'Creating bash completion script: {comp_path.as_posix()}', file=sys.stderr)
    with comp_src.open('r') as in_file, comp_path.open('w') as out_file:
        out_file.write(in_file.read())

    import platform
    if platform.system().lower() == 'windows':
        print('To enable tab completion, add the following lines to your ~/.bashrc or ~/.bash_profile:')
        print('export ARGCOMPLETE_USE_TEMPFILES=1', file=sys.stderr)
    else:
        print('To enable tab completion, add the following line to your ~/.bashrc or ~/.bash_profile:')

    try:
        rel_path = '~/' + comp_path.relative_to(Path.home()).as_posix()
    except Exception:
        rel_path = comp_path.as_posix()

    print(f'source {rel_path}')
    print('=' * 100, file=sys.stderr)
