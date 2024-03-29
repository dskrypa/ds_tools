"""
:author: Doug Skrypa
"""

from sys import stderr
from typing import Callable, Sequence, Any, Optional, Union, Collection, TypeVar

from ..output.color import colored
from ..output.terminal import uprint
from .exceptions import InputValidationException
from .parsers import parse_yes_no, parse_int

__all__ = ['get_input', 'choose_item']

_NotSet = object()

Color = Union[int, str, None]
T = TypeVar('T')
PV = TypeVar('PV')
DV = TypeVar('DV')


def get_input(
    prompt: str,
    skip: bool = False,
    retry: int = 0,
    parser: Callable[[str], PV] = parse_yes_no,
    *,
    default: DV = _NotSet,
    input_func: Callable[[str], str] = input,
) -> Union[PV, DV]:
    """
    Prompt the user for input, and parse the results.  May be skipped by providing a default value and setting ``skip``
    to True.

    :param prompt: The prompt for user input
    :param skip: If True, the ``default`` parameter is required and will be returned without prompting the user
    :param retry: Number of attempts to allow users to retry providing input when validation fails
    :param parser: A function that takes a single positional argument and returns the value that should be used, or
      raises a :class:`.InputValidationException` when given incorrect input (default: :func:`.parse_yes_no`)
    :param default: The default value to return when ``skip`` is True
    :param input_func: The callable to use to receive user input.  Defaults to :func:`python:input`
    :return: The value from the given ``parser`` function
    """
    if skip:
        if default is _NotSet:
            raise ValueError(f'Unable to skip user prompt without a default value: {prompt!r}')
        return default
    suffix = ' ' if not prompt.endswith(' ') else ''
    prompt = prompt + suffix

    while retry >= 0:
        try:
            user_input = input_func(prompt)
        except EOFError as e:
            raise InputValidationException('Unable to read stdin (this is often caused by piped input)') from e

        try:
            return parser(user_input)
        except InputValidationException as e:
            retry -= 1
            if retry < 0:
                raise
            print(str(e), file=stderr)

    raise InputValidationException('Unable to get user input')


def choose_item(
    items: Collection[T],
    name: str = 'value',
    source: Any = '',
    *,
    before: Optional[str] = None,
    retry: int = 0,
    before_color: Color = None,
    prompt_color: Color = 14,
    error_color: Color = 9,
    repr_func: Callable[[Any], str] = repr,
) -> T:
    """
    Given a list of items from which only one value can be used, prompt the user to choose an item.  If only one item
    exists in the provided sequence, then that item is returned with no prompt.

    :param items: A sequence or sortable collection of items to choose from
    :param name: The name of the item to use in messages/prompts
    :param source: Where the items came from
    :param before: A message to be printed before listing the items to choose from (default: automatically generated
      using the provided name and source)
    :param before_color: The ANSI color to use for the before text
    :param prompt_color: The ANSI color to use for the user prompt
    :param error_color: The ANSI color to use for the error if an invalid index is chosen
    :param repr_func: The function to use to generate a string representation of each item
    :param retry: Number of attempts to allow users to retry providing input when validation fails
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
