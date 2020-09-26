"""
Extends the CompletionFinder from argcomplete to exclude other subparser actions when completing arguments for a
subparser.

:author: Doug Skrypa
"""

import os
import sys
from argparse import ArgumentError, Namespace

import argcomplete
from argcomplete import CompletionFinder, debug, sys_encoding, split_line


class ArgCompletionFinder(CompletionFinder):
    def __call__(self, arg_parser, *args, exit_method=None, output_stream=None, **kwargs):
        environ = os.environ
        if '_ARGCOMPLETE' not in environ:  # not an argument completion invocation
            return
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
