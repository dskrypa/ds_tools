#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Wrapper around argparse to provide some additional functionality / shortcuts

:author: Doug Skrypa
"""

import inspect
import os
from argparse import ArgumentParser, RawDescriptionHelpFormatter
from collections import OrderedDict, defaultdict
from copy import deepcopy
from itertools import chain

__all__ = ["ArgParser"]

BUG_REPORT = "Report {} bugs to example@fake.com"
DOC_LINK = "hxxp://documentation-example-site.com/base/path/to/docs/"


class Arg:
    """Only used to store positional & keyword args for common args so alternate default values can be provided"""
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs

    def __repr__(self):
        args = (repr(val) for val in self.args)
        kwargs = ("{}={}".format(k, v.__name__ if k == "type" else repr(v)) for k, v in self.kwargs.items())
        return "<{}({})>".format(type(self).__name__, ",".join(chain(args, kwargs)))

    __str__ = __repr__


COMMON_ARGS = {
    "verbosity": ("add_common_arg", Arg("--verbose", "-v", action="count", help="Increase logging verbosity (can specify multiple times)")),
    "extra_cols": ("add_common_sp_arg", Arg("--extra", "-e", action="count", default=0, help="Increase the number of columns displayed (can specify multiple times)")),
    "select": ("add_common_sp_arg", Arg("--select", "-s", help="Nested key to select, using JQ-like syntax")),
    "parallel": ("add_common_sp_arg", Arg("--parallel", "-P", type=int, default=1, help="Maximum number of workers to use in parallel (default: %(default)s)")),
    "dry_run": ("add_common_sp_arg", Arg("--dry_run", "-D", action="store_true", help="Print the actions that would be taken instead of taking them")),
    "yes": ("add_common_sp_arg", Arg("--yes", "-y", action="store_true", help="Confirm all Yes/No prompts")),
}   #: Common argparse arguments; defining them this way increases consistency between scripts


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
        while _caller_file in (this_file, "argparse"):
            try:
                self._caller_file = os.path.basename(inspect.getsourcefile(inspect.stack()[i][0]))
            except TypeError:
                self._caller_file = "{}_interactive".format(this_file)
            except IndexError:
                break
            i += 1

        sig = inspect.Signature.from_function(ArgumentParser.__init__)
        ap_args = sig.bind(None, *args, **kwargs).arguments
        ap_args.pop("self")

        filename_noext = os.path.splitext(self._caller_file)[0]
        epilog = [BUG_REPORT.format(filename_noext)]
        if doc_link is True:
            epilog.append("Online documentation: {}".format(DOC_LINK + "bin.scripts.{}.html".format(filename_noext)))
        elif isinstance(doc_link, str):
            if doc_link.startswith("http://"):
                epilog.append("Online documentation: {}".format(doc_link))
        ap_args.setdefault("epilog", "\n\n".join(epilog))
        ap_args.setdefault("formatter_class", RawDescriptionHelpFormatter)
        ap_args.setdefault("prog", self._caller_file)
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
            desc_fmt = "{}\n\nUse `{} $cmd --help` for more info about each subcommand"
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
                    formatter.start_section("{} {}".format(sp_dest, choice_name))
                    formatter.add_text(sp_choice.full_help(True, False))
                    formatter.end_section()

        if epilog:
            formatter.add_text(self.epilog)
        return formatter.format_help()

    def _interpolated_help(self, action):
        if not action.help:
            return ""
        params = dict(vars(action), prog=self.prog)
        for name in list(params):
            if params[name] == "==SUPPRESS==":
                del params[name]
        for name in list(params):
            if hasattr(params[name], "__name__"):
                params[name] = params[name].__name__
        if params.get("choices") is not None:
            choices_str = ", ".join([str(c) for c in params["choices"]])
            params["choices"] = choices_str
        help_text = action.help % params
        return help_text[0].upper() + help_text[1:]

    def help_as_rst(self, description=True, epilog=True):
        i = " " * 3
        lines = []
        if self.description and description:
            lines += [self.description, ""]

        formatter = self._get_formatter()
        usage = formatter._format_usage(self.usage, self._actions, self._mutually_exclusive_groups, None)
        lines += ["::\n"]
        lines += [i + line for line in usage.splitlines()]

        for action_group in self._action_groups:
            if not action_group._group_actions:
                continue
            desc = action_group.description
            title = action_group.title[0].upper() + action_group.title[1:]
            lines += ["", "{}{}".format(title, (": " + desc) if desc else ""), "", ".. list-table::"]
            agi = " " * 3
            actions = []
            for action in action_group._group_actions:
                positional = not any(a.startswith("-") for a in action.option_strings)
                if action.help != "==SUPPRESS==":
                    if action.option_strings:
                        if action.nargs == 0:
                            meta = None
                        elif action.metavar is not None:
                            meta = action.metavar
                        else:
                            meta = action.dest

                        opts = ("{} {}".format(opt, meta) if meta else opt for opt in sorted(action.option_strings))
                        act_options = ", ".join("``{}``".format(opt) for opt in opts)
                    else:
                        act_options = action.dest

                    act_help = self._interpolated_help(action)
                    if (not positional) and action.required and ("required" not in act_help.lower()):
                        act_help += " (required)"
                    act_choices = ", ".join(sorted(str(choice) for choice in action.choices)) if action.choices else ""
                    actions.append((act_options, act_help, act_choices))

            if actions:
                opts_width = max(len(action[0]) for action in actions)
                desc_width = max(len(action[i]) for i in (1, 2) for action in actions) + 20
                lines += [agi + ":widths: {} {}".format(opts_width, desc_width), ""]

                for act_options, act_help, act_choices in actions:
                    lines += [agi + "* - | {}".format(act_options)]
                    if act_help:
                        lines += [agi + "  - | {}".format(act_help)]
                    if act_choices:
                        fmt = "  - | Choices: {}" if not act_help else "    | Choices: {}"
                        lines += [agi + fmt.format(act_choices)]
                    if not (act_help or act_choices):
                        lines += [agi + "  - | "]

        if self.subparsers:
            lines += ["", "Sub-Commands", "=" * 12, ""]
            for sp_dest, sp in self.subparsers.items():
                sp_unique = OrderedDict()
                aliases = defaultdict(set)
                for choice_name, sp_choice in sp.choices.items():
                    primary = sp_choice.prog.split()[-1]
                    if primary != choice_name:
                        aliases[primary].add(choice_name)
                    else:
                        sp_unique[choice_name] = sp_choice

                for choice_name, sp_choice in sp_unique.items():
                    sp_aliases = sorted(aliases[choice_name])
                    if sp_aliases:
                        choice_name = "{} / {}".format(choice_name, " / ".join(sp_aliases))
                    sp_title = "{}: {}".format(sp_dest, choice_name)
                    lines += ["", sp_title, "-" * len(sp_title), ""]
                    lines += sp_choice.help_as_rst(True, False).splitlines()

        if self.epilog and epilog:
            lines += ["", self.epilog]
        return "\n".join(lines)

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
            sp_group = self.add_subparsers(dest=dest, title="subcommands")
        return sp_group.add_parser(name, help=help or help_desc, description=description or help_desc, _caller_file=self._caller_file, **kwargs)

    def add_constant(self, key, value):
        self.__constants[key] = value

    def add_common_sp_arg(self, *args, **kwargs):
        """Add an argument with the given parameters to every subparser in this ArgParser, or itself if it has none"""
        if self.subparsers:
            for subparser in set(chain.from_iterable(sp.choices.values() for sp in self.subparsers.values())):
                subparser.add_argument(*args, **kwargs)
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
            kvargs["default"] = default
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
            msg = "unrecognized arguments: {}".format(" ".join(argv))
            if self.subparsers:
                self.error("{}\nnote: subcommand args must be provided after the subcommand (use --help for more details)".format(msg))
            self.error(msg + " (use --help for more details)")

        if req_subparser_value:
            for sp in self.subparsers:
                if getattr(parsed, sp) is None:
                    self.error("missing required positional argument: {} (use --help for more details)".format(sp))

        parsed.__dict__.update(self.__constants)
        update_subparser_constants(self, parsed)
        return parsed


def update_subparser_constants(parser, parsed):
    for dest, subparsers in parser.subparsers.items():
        chosen_sp = parsed.__dict__[dest]
        for sp_name, subparser in subparsers.choices.items():
            if sp_name == chosen_sp:
                parsed.__dict__.update(subparser._ArgParser__constants)
                update_subparser_constants(subparser, parsed)
