"""
Extends the CompletionFinder from argcomplete to exclude other subparser actions when completing arguments for a
subparser.

:author: Doug Skrypa
"""

import argparse
import os
import sys
from argparse import ArgumentError, Namespace
from pathlib import Path

import argcomplete
from argcomplete import CompletionFinder, debug, sys_encoding, split_line
from argcomplete import completers, action_is_greedy, action_is_open, action_is_satisfied
from argcomplete.completers import SuppressCompleter


class ArgCompletionFinder(CompletionFinder):
    def __call__(self, arg_parser, *args, exit_method=None, output_stream=None, ensure_comp_possible=True, **kwargs):
        environ = os.environ
        if '_ARGCOMPLETE' not in environ:  # not an argument completion invocation
            return ensure_argcomplete_is_available(ensure_comp_possible)
        exit_method = exit_method or os._exit  # noqa
        try:
            argcomplete.debug_stream = os.fdopen(9, 'w')
        except OSError:
            argcomplete.debug_stream = sys.stderr
        debug()

        if output_stream is None:
            filename = environ.get('_ARGCOMPLETE_STDOUT_FILENAME')
            if filename is not None:
                debug(f'Using output file {filename}')
                output_stream = open(filename, 'wb')

        if output_stream is None:
            try:
                output_stream = os.fdopen(8, 'wb')
            except OSError:
                debug('Unable to open fd 8 for writing, quitting')
                exit_method(1)

        ifs = environ.get('_ARGCOMPLETE_IFS', '\013')
        if len(ifs) != 1:
            debug(f'Invalid value for IFS, quitting [{ifs}]')
            exit_method(1)

        dfs = environ.get('_ARGCOMPLETE_DFS')
        if dfs and len(dfs) != 1:
            debug(f'Invalid value for DFS, quitting [{dfs}]')
            exit_method(1)

        comp_point = int(environ['COMP_POINT'])
        comp_line = environ['COMP_LINE']
        cword_prequote, cword_prefix, cword_suffix, comp_words, last_wordbreak_pos = split_line(comp_line, comp_point)
        start = int(environ['_ARGCOMPLETE']) - 1  # set by shell script to indicate where comp_words start
        comp_words = comp_words[start:]
        if cword_prefix and cword_prefix[0] in arg_parser.prefix_chars and '=' in cword_prefix:
            # Special case for when the current word is '--optional=PARTIAL_VALUE'. Give the optional to the parser.
            comp_words.append(cword_prefix.split('=', 1)[0])

        debug(
            f'\nLINE: {comp_line!r}\nPOINT: {comp_point!r}\nPREQUOTE: {cword_prequote!r}\nPREFIX: {cword_prefix!r}',
            f'\nSUFFIX: {cword_suffix!r}\nWORDS:{comp_words}'
        )
        try:
            parsed, argv = arg_parser._parse_known_args(comp_words, Namespace())
        except ArgumentError:
            pass
        else:
            arg_parser = arg_parser._get_subparser(parsed.__dict__)  # noqa

        self.__init__(arg_parser, *args, **kwargs)
        completions = self._get_completions(comp_words, cword_prefix, cword_prequote, last_wordbreak_pos)
        if dfs:
            display_completions = {
                part: v.replace(ifs, ' ') if v else '' for k, v in self._display_completions.items() for part in k
            }
            completions = [dfs.join((key, display_completions.get(key) or '')) for key in completions]

        debug('\nReturning completions:', completions)
        output_stream.write(ifs.join(completions).encode(sys_encoding))
        output_stream.flush()
        argcomplete.debug_stream.flush()
        exit_method(0)

    def _complete_active_option(self, parser, next_positional, cword_prefix, parsed_args, completions):
        # Patched to make active actions readable for debugging
        active_actions = parser.active_actions
        debug(f'\nActive actions (L={len(active_actions)}):\n', '\n'.join(f'  - {a}' for a in active_actions))

        isoptional = cword_prefix and cword_prefix[0] in parser.prefix_chars
        optional_prefix = ''
        greedy_actions = [x for x in active_actions if action_is_greedy(x, isoptional)]
        if greedy_actions:
            assert len(greedy_actions) == 1, 'expect at most 1 greedy action'
            # This means the action will fail to parse if the word under the cursor is not given
            # to it, so give it exclusive control over completions (flush previous completions)
            debug('Resetting completions because', greedy_actions[0], 'must consume the next argument')
            self._display_completions = {}
            completions = []
        elif isoptional:
            if '=' in cword_prefix:
                # Special case for when the current word is '--optional=PARTIAL_VALUE'.
                # The completer runs on PARTIAL_VALUE. The prefix is added back to the completions
                # (and chopped back off later in quote_completions() by the COMP_WORDBREAKS logic).
                optional_prefix, _, cword_prefix = cword_prefix.partition('=')
            else:
                # Only run completers if current word does not start with - (is not an optional)
                return completions

        complete_remaining_positionals = False
        # Use the single greedy action (if there is one) or all active actions.
        for active_action in greedy_actions or parser.active_actions:
            if not active_action.option_strings:  # action is a positional
                if action_is_open(active_action):
                    # Any positional arguments after this may slide down into this action if more arguments are added
                    # (since the user may not be done yet), so it is extremely difficult to tell which completers to
                    # run. Running all remaining completers will probably show more than the user wants but it also
                    # guarantees we won't miss anything.
                    complete_remaining_positionals = True
                if not complete_remaining_positionals:
                    if action_is_satisfied(active_action) and not action_is_open(active_action):
                        debug('Skipping', active_action)
                        continue

            debug('Activating completion for', active_action, active_action._orig_class)
            completer = getattr(active_action, 'completer', None)

            if completer is None:
                # noinspection PyUnresolvedReferences
                if active_action.choices is not None and not isinstance(active_action, argparse._SubParsersAction):
                    completer = completers.ChoicesCompleter(active_action.choices)
                elif not isinstance(active_action, argparse._SubParsersAction):  # noqa
                    completer = self.default_completer

            if completer:
                if isinstance(completer, SuppressCompleter) and completer.suppress():
                    continue
                elif callable(completer):
                    completions_from_callable = [
                        c for c in completer(
                            prefix=cword_prefix, action=active_action, parser=parser, parsed_args=parsed_args
                        )
                        if self.validator(c, cword_prefix)
                    ]

                    if completions_from_callable:
                        completions += completions_from_callable
                        if isinstance(completer, completers.ChoicesCompleter):
                            self._display_completions.update(
                                [[(x,), active_action.help] for x in completions_from_callable]  # noqa
                            )
                        else:
                            self._display_completions.update([[(x,), ''] for x in completions_from_callable])  # noqa
                else:
                    debug('Completer is not callable, trying the readline completer protocol instead')
                    for i in range(9999):
                        next_completion = completer.complete(cword_prefix, i)  # noqa
                        if next_completion is None:
                            break
                        if self.validator(next_completion, cword_prefix):
                            self._display_completions.update({(next_completion,): ''})
                            completions.append(next_completion)
                if optional_prefix:
                    completions = [optional_prefix + '=' + completion for completion in completions]
                debug('Completions:', completions)

        return completions


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
