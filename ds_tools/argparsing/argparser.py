"""
Wrapper around argparse to provide some additional functionality / shortcuts

:author: Doug Skrypa
"""

import inspect
import os
# noinspection PyUnresolvedReferences
from argparse import ArgumentParser, RawDescriptionHelpFormatter, _ArgumentGroup, Namespace
from pathlib import Path

__all__ = ['ArgParser']


class ArgParser(ArgumentParser):
    """
    Wrapper around the argparse ArgumentParser to provide some additional functionality / shortcuts

    :param args: Positional args to pass to :class:`argparse.ArgumentParser`
    :param str docs_url: A url to provide as a link to documentation
    :param Path|None _caller_path: Filename of the file that created this ArgParser (automatically detected - this
      argument should not be provided by users)
    :param kwargs: Keyword args to pass to :class:`argparse.ArgumentParser`
    """
    _caller_path = None
    _docs_url = None
    _email = None
    _version = ''

    def __init__(self, *args, docs_url=None, email=None, _caller_path=None, _version=None, **kwargs):
        if '_ARGCOMPLETE' in os.environ:
            super().__init__(*args, **kwargs)
        else:
            if _caller_path:
                self._caller_path = _caller_path
                self._docs_url = docs_url
                self._email = email
                self._version = _version or ''
            else:
                try:
                    top_level_frame_info = inspect.stack()[-1]
                    g = top_level_frame_info.frame.f_globals
                    _email, version, repo_url = g.get('__author_email__'), g.get('__version__'), g.get('__url__')
                    self._caller_path = Path(inspect.getsourcefile(top_level_frame_info[0]))
                except Exception:
                    self._caller_path = Path(__file__)
                    self._docs_url = docs_url
                    self._email = email
                    self._version = _version or ''
                else:
                    self._docs_url = docs_url or docs_url_from_repo_url(repo_url)
                    self._email = email or _email
                    self._version = _version or version or ''

            if self._version and not self._version.startswith(' ['):
                self._version = f' [ver. {self._version}]'

            sig = inspect.Signature.from_callable(ArgumentParser.__init__)
            ap_args = sig.bind(None, *args, **kwargs).arguments
            ap_args.pop('self')

            epilog = []
            if self._email:
                epilog .append(f'Report {self._caller_path.name}{self._version} bugs to {self._email}')
            if self._docs_url:
                epilog.append(f'Online documentation: {self._docs_url}')
            ap_args.setdefault('epilog', '\n\n'.join(epilog))
            ap_args.setdefault('formatter_class', RawDescriptionHelpFormatter)
            ap_args.setdefault('prog', self._caller_path.name)
            super().__init__(**ap_args)
        self.__constants = {}
        self.__mutually_exclusive_sets = []

    @property
    def subparsers(self):
        try:
            return {sp.dest: sp for sp in self._subparsers._group_actions}
        except AttributeError:
            return {}

    @property
    def has_subparsers(self) -> bool:
        try:
            return bool(self._subparsers._group_actions)
        except AttributeError:
            return False

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
            desc = desc_fmt.format(self.description, self._caller_path.name)
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

    def add_subparser(self, dest, name, help_desc=None, *, help=None, description=None, **kwargs) -> 'ArgParser':
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

        sub_parser = sp_group.add_parser(
            name,
            help=help or help_desc,
            description=description or help_desc,
            docs_url=self._docs_url,
            email=self._email,
            _caller_path=self._caller_path,
            _version=self._version,
            **kwargs,
        )
        # noinspection PyTypeChecker
        return sub_parser

    def add_constant(self, key, value):
        self.__constants[key] = value

    def add_common_sp_arg(self, *args, **kwargs):
        """Add an argument with the given parameters to every subparser in this ArgParser, or itself if it has none"""
        if self.subparsers:
            for subparser in {val for sp in self.subparsers.values() for val in sp.choices.values()}:
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
        from .utils import COMMON_ARGS
        for arg in args:
            fn_name, a = COMMON_ARGS[arg]
            getattr(self, fn_name)(*a.args, **a.kwargs)

        for arg, default in kwargs.items():
            fn_name, a = COMMON_ARGS[arg]
            kvargs = a.kwargs.copy()
            kvargs['default'] = default
            getattr(self, fn_name)(*a.args, **kvargs)

    def add_mutually_exclusive_arg_sets(self, *groups: _ArgumentGroup):
        """
        Creates a mutually exclusive set of arguments such that if any non-default values are provided for arguments
        in more than 1 of the groups, then the parser will exit.

        Note that the arguments in one of the groups cannot be required if that group is not used in a pair of exclusive
        groups.

        :param groups: Sets of args or argparse group objects that should be mutually exclusive across groups
        """
        group_set = []
        for group in groups:
            try:
                group_set.append({action.dest for action in group._group_actions})
            except AttributeError:
                group_set.append(group)

        self.__mutually_exclusive_sets.append(group_set)
        # TODO: add handling for "maybe required" args that are not allowed because of something in the other group
        #  having been specified.   ... Maybe figure out way to generate a unique list of all args for the chain of
        #  subparsers that were used, to get the unique Argument objects and check the ones in that subparser chain
        #  that are in the exclusive groups.... or something like that?

    def parse_args(
        self, args=None, namespace=None, req_subparser_value=None, completion=True, ensure_comp_possible=True, **kwargs
    ) -> Namespace:
        """
        Performs the same function as :func:`argparse.ArgumentParser.parse_args`, but handles unrecognized arguments
        differently.  Injects common args that were included in the constructor (done here because all subparsers will
        have been fully initialized by this point).  Provides additional feedback to users.

        :param args: The list of arguments to parse (default: sys.argv)
        :param namespace: A namespace to use (default: it will be created)
        :param bool req_subparser_value: Require a value to be provided for subparsers
        :param bool completion: Whether arg completion should be attempted
        :param bool ensure_comp_possible: Whether arg completion installation should be verified
        :param kwargs: Keyword args to pass to :class:`ArgCompletionFinder`
        :return: Namespace containing the parsed arguments
        """
        if completion:
            try:
                from .argcompleter import ArgCompletionFinder  # noqa
            except ImportError:
                pass
            else:
                ArgCompletionFinder()(self, ensure_comp_possible=ensure_comp_possible, **kwargs)
        from .utils import update_subparser_constants
        parsed, argv = self.parse_known_args(args, namespace)
        if argv:
            msg = 'unrecognized arguments: {}'.format(' '.join(argv))
            suffix = ' (use --help for more details)'
            if self.subparsers:
                self.error(f'{msg}\nnote: subcommand args must be provided after the subcommand{suffix}')
            self.error(msg + suffix)

        req_sp_val = self.has_subparsers if req_subparser_value is None else req_subparser_value
        if req_sp_val and (sp := next((sp for sp in self.subparsers if getattr(parsed, sp) is None), None)):
            self.error(f'missing required positional argument: {sp} (use --help for more details)')  # noqa

        parsed.__dict__.update(self.__constants)
        update_subparser_constants(self, parsed)
        self._resolve_mutually_exclusive_sets(parsed)
        return parsed

    def _resolve_mutually_exclusive_sets(self, parsed):
        from .utils import get_default_value
        for exclusive_sets in self.__mutually_exclusive_sets:
            arg_sets = []
            for group in exclusive_sets:
                group_values = {k: parsed.__dict__.get(k) for k in group}
                if non_defaults := {k for k, v in group_values.items() if v != get_default_value(self, parsed, k)}:
                    arg_sets.append(non_defaults)
                    if len(arg_sets) > 1:
                        self.error('Argument(s) {} cannot be combined with {}'.format(*arg_sets))

    def _get_subparser(self, kwargs):
        parser = self
        for dest, sp_group in self.subparsers.items():
            try:
                name = kwargs[dest]
            except KeyError:
                pass
            else:
                parser = sp_group._name_parser_map[name]
                break

        if parser is not self:
            try:
                return parser._get_subparser(kwargs)
            except AttributeError:
                pass
        return parser

    def parse_with_dynamic_args(self, from_field, args=None, namespace=None, req_subparser_value=False):
        import re
        from itertools import chain
        from yaml import safe_load
        from yaml.parser import ParserError

        parsed = self.parse_args(args, namespace, req_subparser_value)
        try:
            dynamic = getattr(parsed, from_field)
        except AttributeError:
            return parsed, None

        # Remove the action that contains the dynamic arguments from this parser or the active subparser
        dynamic_str = ' '.join(dynamic) if not isinstance(dynamic, str) else dynamic
        # print(f'Base args: {parsed.__dict__}\nProcessing args: {dynamic_str!r}')
        parser = self._get_subparser(parsed.__dict__)
        if rm_action := next((act for act in parser._actions if act.dest == from_field), None):
            # print(f'Removing action: {rm_action}'
            parser._remove_action(rm_action)

        # Add discovered arguments to the active parser
        known_options = set(chain.from_iterable(act.option_strings for act in chain(self._actions, parser._actions)))
        for m in re.finditer(r'(?:^|\s)(--?\S+?)[=\s]', dynamic_str):
            key = m.group(1)
            # print(f'Found key: {key!r}')
            if key not in known_options:
                parser.add_argument(key, nargs='+')
            # else:
            #     print(f'Skipping known key: {key!r}')

        def _get_default(key):
            base_default = self.get_default(key)
            sp_default = parser.get_default(key)
            if base_default is None and sp_default is not None:
                return sp_default
            elif base_default is not None and sp_default is None:
                return base_default
            return sp_default

        re_parsed = self.parse_args(args, namespace, req_subparser_value)
        newly_parsed = {}
        for k, v in re_parsed._get_kwargs():
            try:
                orig = parsed.__dict__[k]
            except KeyError:
                try:
                    # Note: using yaml.safe_load to handle str/int/float/bool automatically
                    newly_parsed[k] = safe_load(' '.join(v))
                except ParserError:
                    newly_parsed[k] = ' '.join(v)
            else:
                if v != orig:
                    default = _get_default(k)
                    # print(f'Different value found for key={k!r}: {orig=!r} new={v!r} {default=!r}')
                    if orig == default or v != default:
                        # print(f'Updating parsed[{k!r}] => {v!r}')
                        parsed.__dict__[k] = v

        # print(f're-parsed: {re_parsed.__dict__}\nnewly parsed: newly_parsed{}')
        # print(f'Final parsed args: {parsed.__dict__}')
        return parsed, newly_parsed

    def __enter__(self):
        """Allow using ArgParsers as context managers to help organize large subparser sections when defining parsers"""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return


def docs_url_from_repo_url(repo_url):
    if repo_url and repo_url.startswith('https://github.com'):
        from urllib.parse import urlparse

        try:
            user, repo = urlparse(repo_url).path[1:].split('/')
        except Exception:
            return None
        else:
            return f'https://{user}.github.io/{repo}/'
    return None
