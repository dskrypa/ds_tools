"""
Convenience functions for pretty reprs using rich.
"""

from rich.console import Console
from rich.highlighter import NullHighlighter
from rich.pretty import Pretty, pretty_repr
from rich.text import Text

__all__ = ['rich_repr', 'print_rich_repr']

CONSOLE = Console(highlight=False)
NULL_HIGHLIGHTER = NullHighlighter()


def print_rich_repr(obj):
    """Print a non-highlighted (symmetrical) pretty repr of the given object using rich."""
    CONSOLE.print(Pretty(obj, highlighter=NULL_HIGHLIGHTER), soft_wrap=True)


def rich_repr(obj, max_width: int = 80, soft_wrap: bool = False) -> str:
    """Render a non-highlighted (symmetrical) pretty repr of the given object using rich."""
    text = pretty_repr(obj, max_width=max_width)
    if soft_wrap:
        pretty_text = Text(text, style='pretty', no_wrap=True, overflow='ignore')
    else:
        pretty_text = Text(text, style='pretty')
    return str(pretty_text)
