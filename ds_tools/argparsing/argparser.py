"""
Wrapper around argparse to provide some additional functionality / shortcuts

:author: Doug Skrypa
"""

import inspect
import os
import re
from argparse import ArgumentParser, RawDescriptionHelpFormatter
from copy import deepcopy
from itertools import chain

import yaml
from yaml.parser import ParserError

from .utils import COMMON_ARGS, update_subparser_constants

__all__ = ['ArgParser']

BUG_REPORT = 'Report {} bugs to example@fake.com'
DOC_LINK = 'hxxp://documentation-example-site.com/base/path/to/docs/'


class ArgParser(ArgumentParser):
    """
    Wrapper around the argparse ArgumentParser to provide some additional functionality / shortcuts

    :param args: Positional args to pass to :class:`argparse.ArgumentParser`
    :param bool|str doc_link: True to provide the default URL, or a str starting with ``http://`` to include literally
    :param str|None _caller_file: Filename of the file that created this ArgParser (automatically detected - this
      argument should not be provided by users)
    :param kwargs: Keyword args to pass to :class:`argparse.ArgumentParser`
    """
    def __init__(self, *args, doc_link=False, _caller_file=None, **kwargs):
        this_file = os.path.splitext(os.path.basename(__file__))[0]
        self._caller_file = _caller_file or this_file
        i = 1
        while _caller_file in (this_file, 'argparse'):
            try:
                self._caller_file = os.path.basename(inspect.getsourcefile(inspect.stack()[i][0]))
            except TypeError:
                self._caller_file = '{}_interactive'.format(this_file)
            except IndexError:
                break
            i += 1

        sig = inspect.Signature.from_function(ArgumentParser.__init__)
        ap_args = sig.bind(None, *args, **kwargs).arguments
        ap_args.pop('self')

        filename_noext = os.path.splitext(self._caller_file)[0]
        epilog = [BUG_REPORT.format(filename_noext)]
        if doc_link is True:
            epilog.append('Online documentation: {}'.format(DOC_LINK + 'bin.scripts.{}.html'.format(filename_noext)))
        elif isinstance(doc_link, str):
            if doc_link.startswith('http://'):
                epilog.append('Online documentation: {}'.format(doc_link))
        ap_args.setdefault('epilog', '\n\n'.join(epilog))
        ap_args.setdefault('formatter_class', RawDescriptionHelpFormatter)
        ap_args.setdefault('prog', self._caller_file)
        super().__init__(**ap_args)
        self.__constants = {}

    @property
    def subparsers(self):
        try:
            return {sp.dest: sp for sp in self._subparsers._group_actions}
        except AttributeError:
            return {}

    @property
    def groups(self):
        try:
            return {group.title: group for group in self._action_groups}
        except AttributeError:
            return {}

    def format_help(self):
        formatter = self._get_formatter()
        formatter.add_usage(self.usage, self._actions, self._mutually_exclusive_groups)

        if self.subparsers:
            desc_fmt = '{}\n\nUse `{} $cmd --help` for more info about each subcommand'
            desc = desc_fmt.format(self.description, self._caller_file)
        else:
            desc = self.description
        formatter.add_text(desc)

        # positionals, optionals and user-defined groups
        for action_group in self._action_groups:
            formatter.start_section(action_group.title)
            formatter.add_text(action_group.description)
            formatter.add_arguments(action_group._group_actions)
            formatter.end_section()

        formatter.add_text(self.epilog)
        return formatter.format_help()

    def full_help(self, description=True, epilog=True):
        """
        Intended only for generating a full dump of help text options for this parser and its subparsers for
        automatically generated documentation.

        :param bool description: Include the parser's description
        :param bool epilog: Include the parser's epilog
        :return str: The formatted full help text
        """
        formatter = self._get_formatter()
        formatter.add_usage(self.usage, self._actions, self._mutually_exclusive_groups)

        if description:
            formatter.add_text(self.description)

        # positionals, optionals and user-defined groups
        for action_group in self._action_groups:
            formatter.start_section(action_group.title)
            formatter.add_text(action_group.description)
            formatter.add_arguments(action_group._group_actions)
            formatter.end_section()

        if self.subparsers:
            for sp_dest, sp in self.subparsers.items():
                for choice_name, sp_choice in sp.choices.items():
                    formatter.start_section('{} {}'.format(sp_dest, choice_name))
                    formatter.add_text(sp_choice.full_help(True, False))
                    formatter.end_section()

        if epilog:
            formatter.add_text(self.epilog)
        return formatter.format_help()

    def add_subparser(self, dest, name, help_desc=None, *, help=None, description=None, **kwargs):
        """
        Add a subparser for a subcommand to the subparser group with the given destination variable name.  Creates the
        group if it does not already exist.

        :param str dest: The subparser group destination for this subparser
        :param str name: The name of the subcommand/subparser to add
        :param str help_desc: The text to be used as both the help and description for this subcommand
        :param str help: The help text to be printed for ``$script --help`` for this subcommand
        :param str description: The description to be printed for ``$script $name --help``
        :param kwargs: Keyword args to pass to the :func:`add_parser` function
        :return: The parser that was created
        """
        try:
            sp_group = self.subparsers[dest]
        except KeyError:
            sp_group = self.add_subparsers(dest=dest, title='subcommands')
        return sp_group.add_parser(name, help=help or help_desc, description=description or help_desc, _caller_file=self._caller_file, **kwargs)

    def add_constant(self, key, value):
        self.__constants[key] = value

    def add_common_sp_arg(self, *args, **kwargs):
        """Add an argument with the given parameters to every subparser in this ArgParser, or itself if it has none"""
        if self.subparsers:
            for subparser in set(chain.from_iterable(sp.choices.values() for sp in self.subparsers.values())):
                subparser.add_common_arg(*args, **kwargs)
        else:
            self.add_argument(*args, **kwargs)

    def add_common_arg(self, *args, **kwargs):
        """Add an argument with the given parameters to this ArgParser and every subparser in it"""
        self.add_argument(*args, **kwargs)
        if self.subparsers:
            self.add_common_sp_arg(*args, **kwargs)

    def include_common_args(self, *args, **kwargs):
        """
        :param str args: One or more strs that are keys in :data:`COMMON_ARGS`
        """
        for arg in args:
            fn_name, a = COMMON_ARGS[arg]
            getattr(self, fn_name)(*a.args, **a.kwargs)

        for arg, default in kwargs.items():
            fn_name, a = COMMON_ARGS[arg]
            kvargs = deepcopy(a.kwargs)
            kvargs['default'] = default
            getattr(self, fn_name)(*a.args, **kvargs)

    def parse_args(self, args=None, namespace=None, req_subparser_value=False):
        """
        Performs the same function as :func:`argparse.ArgumentParser.parse_args`, but handles unrecognized arguments
        differently.  Injects common args that were included in the constructor (done here because all subparsers will
        have been fully initialized by this point).  Provides additional feedback to users.

        :param args: The list of arguments to parse (default: sys.argv)
        :param namespace: A namespace to use (default: it will be created)
        :param bool req_subparser_value: Require a value to be provided for subparsers
        :return: Namespace containing the parsed arguments
        """
        parsed, argv = self.parse_known_args(args, namespace)
        if argv:
            msg = 'unrecognized arguments: {}'.format(' '.join(argv))
            if self.subparsers:
                self.error('{}\nnote: subcommand args must be provided after the subcommand (use --help for more details)'.format(msg))
            self.error(msg + ' (use --help for more details)')

        if req_subparser_value:
            for sp in self.subparsers:
                if getattr(parsed, sp) is None:
                    self.error('missing required positional argument: {} (use --help for more details)'.format(sp))

        parsed.__dict__.update(self.__constants)
        update_subparser_constants(self, parsed)
        return parsed

    def parse_with_dynamic_args(self, from_field, args=None, namespace=None, req_subparser_value=False):
        parsed = self.parse_args(args, namespace, req_subparser_value)
        try:
            dynamic = getattr(parsed, from_field)
        except AttributeError:
            return parsed, None

        dynamic_str = ' '.join(dynamic) if not isinstance(dynamic, str) else dynamic
        # print('Base args: {}\nProcessing args: {!r}'.format(parsed.__dict__, dynamic_str))
        parser = type(self)(parents=[self], add_help=False)
        pat = re.compile(r'(?:^|\s)(--?\S+?)[=\s]')
        for m in pat.finditer(dynamic_str):
            key = m.group(1)
            # print('Found key: {!r}'.format(key))
            parser.add_argument(key, nargs='+')

        re_parsed = parser.parse_args(dynamic)
        newly_parsed = {}
        for k, v in re_parsed._get_kwargs():
            try:
                orig = parsed.__dict__[k]
            except KeyError:
                try:
                    # Note: using yaml.safe_load to handle str/int/float/bool automatically
                    newly_parsed[k] = yaml.safe_load(' '.join(v))
                except ParserError:
                    newly_parsed[k] = ' '.join(v)
            else:
                if self.get_default(k) == orig and v != orig:
                    # print('Updating parsed[{!r}] => {!r}'.format(k, v))
                    parsed.__dict__[k] = v

        # print('re-parsed: {}\nnewly parsed: {}'.format(re_parsed.__dict__, newly_parsed))
        # print('Final parsed args: {}'.format(parsed.__dict__))
        return parsed, newly_parsed
