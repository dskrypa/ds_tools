"""
Typing helpers to make it easier to use Signature.from_callable for automatic conversion of positional to keyword args.
"""

from argparse import ArgumentParser as _ArgumentParser, _SubParsersAction  # noqa

__all__ = ['ArgumentParser', 'SubParsersAction']


class ArgumentParser(_ArgumentParser):
    def add_argument_group(
        self, title=None, description=None, *, prefix_chars=None, argument_default=None, conflict_handler=None
    ):
        return super().add_argument_group(
            title=title, description=description, prefix_chars=prefix_chars,
            argument_default=argument_default, conflict_handler=conflict_handler,
        )

    def add_mutually_exclusive_group(self, *, required=False):
        return super().add_mutually_exclusive_group(required=required)

    def add_subparsers(
        self, *, title=None, description=None, prog=None, dest=None, help=None,  # noqa
        action=None, option_string=None, required=None, metavar=None,
    ):
        return super().add_subparsers(
            title=title, description=description, prog=prog, dest=dest, help=help,
            action=action, option_string=option_string, required=required, metavar=metavar,
        )


class SubParsersAction(_SubParsersAction):
    def add_parser(self, name, *, aliases=None, description=None, prog=None, help=None):  # noqa
        return super().add_parser(name, aliases=aliases, description=description, prog=prog, help=help)
