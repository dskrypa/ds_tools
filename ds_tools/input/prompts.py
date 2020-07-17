"""
:author: Doug Skrypa
"""

import logging
from typing import Callable, Sequence, Any, Optional, Union, Collection

try:
    from prompt_toolkit import ANSI, prompt as input
except ImportError:
    def ANSI(text):
        return text

from ..core.exceptions import InputValidationException
from ..output.color import colored
from ..output.terminal import uprint
from .parsers import parse_yes_no, parse_int

__all__ = ['get_input', 'choose_item']
log = logging.getLogger(__name__)
_NotSet = object()
Color = Union[int, str, None]


def get_input(prompt: str, skip=False, retry: int = 0, parser: Callable = parse_yes_no, *, default=_NotSet):
    """
    Prompt the user for input, and parse the results.  May be skipped by providing a default value and setting ``skip``
    to True.

    :param str prompt: The prompt for user input
    :param bool skip: If True, the ``default`` parameter is required and will be returned without prompting the user
    :param int retry: Number of attempts to allow users to retry providing input when validation fails
    :param parser: A function that takes a single positional argument and returns the value that should be used, or
      raises a :class:`InputValidationException` when given incorrect input (default: :func:`parse_yes_no`)
    :param default: The default value to return when ``skip`` is True
    :return: The value from the given ``parser`` function
    """
    if skip:
        if default is _NotSet:
            raise ValueError('Unable to skip user prompt without a default value: {!r}'.format(prompt))
        return default
    suffix = ' ' if not prompt.endswith(' ') else ''

    while retry >= 0:
        try:
            user_input = input(ANSI(prompt + suffix))
        except EOFError as e:
            raise InputValidationException('Unable to read stdin (this is often caused by piped input)') from e

        try:
            return parser(user_input)
        except InputValidationException as e:
            retry -= 1
            if retry < 0:
                raise
            log.error(e)
    raise InputValidationException('Unable to get user input')


def choose_item(
        items: Collection[Any], name: str = 'value', source: Any = '', *, before: Optional[str] = None,
        before_color: Color = None, prompt_color: Color = 14, error_color: Color = 9, repr_func: Callable = repr,
        retry: int = 0
) -> Any:
    """
    Given a list of items from which only one value can be used, prompt the user to choose an item.  If only one item
    exists in the provided sequence, then that item is returned with no prompt.

    :param Collection items: A sequence or sortable collection of items to choose from
    :param str name: The name of the item to use in messages/prompts
    :param source: Where the items came from
    :param str before: A message to be printed before listing the items to choose from (default: automatically generated
      using the provided name and source)
    :param str|int|None before_color: The ANSI color to use for the before text
    :param str|int|None prompt_color: The ANSI color to use for the user prompt
    :param str|int|None error_color: The ANSI color to use for the error if an invalid index is chosen
    :param Callable repr_func: The function to use to generate a string representation of each item
    :param int retry: Number of attempts to allow users to retry providing input when validation fails
    :return: The selected item
    """
    if not isinstance(items, Sequence):
        items = sorted(items)
    if not items:
        raise ValueError(f'No {name}s found{_prepare_source(source)}')
    elif len(items) == 1:
        return items[0]
    else:
        uprint(colored(before or f'Found multiple {name}s{_prepare_source(source)}:', before_color))
        fmt = f' - {{:>{len(str(len(items)))}d}}: {{}}'
        for i, item in enumerate(items):
            uprint(fmt.format(i, repr_func(item)))

        prompt = colored(f'Which {name} should be used [specify the number]?', prompt_color)
        choice = get_input(prompt, parser=parse_int, retry=retry)
        try:
            return items[choice]
        except IndexError as e:
            error_msg = colored(f'Invalid {name} index - choose a value between 0 and {len(items) - 1}', error_color)
            raise InputValidationException(error_msg) from e


def _prepare_source(source: Any) -> str:
    if source:
        if not isinstance(source, str):
            source = str(source)
        if not source.startswith(' '):
            source = ' ' + source
        if not source.startswith((' for ', ' from ', ' in ')):
            source = ' for' + source
    return source
