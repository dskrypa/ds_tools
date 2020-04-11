"""
:author: Doug Skrypa
"""

from numbers import Number
from typing import Callable, Any

from yaml import safe_load

from ..core.exceptions import InputValidationException

__all__ = ['parse_yes_no', 'parse_full_yes_no', 'parse_bool', 'parse_with_func', 'parse_int']


def parse_bool(value: Any) -> bool:
    original = value
    if isinstance(value, bool):
        return value
    value = safe_load(value)                # Handles 0/1/true/True/TRUE/false/False/FALSE
    if isinstance(value, (Number, bool)):
        return bool(value)
    elif isinstance(value, str):
        value = value.lower()
        if value in ('t', 'y', 'yes'):
            return True
        elif value in ('f', 'n', 'no'):
            return False
    # ValueError works with argparse to provide a useful error message
    raise ValueError('Unable to parse boolean value from input: {!r}'.format(original))


def parse_yes_no(user_input: str) -> bool:
    """
    Case-insensitive Yes/No input parser

    :param str user_input: Raw user input
    :return bool: True if the provided input started with Y, False if it started with N
    :raises: :class:`InputValidationException` if input did not start with a Y or N
    """
    first_char = _prepare_input(user_input)[0].upper()
    if first_char in ('Y', 'N'):
        return first_char == 'Y'
    raise InputValidationException('Expected "yes"/"y" or "no"/"n"')


def parse_full_yes_no(user_input: str) -> bool:
    """
    Case-insensitive full Yes/No input parser

    :param str user_input: Raw user input
    :return bool: True is the provided input was 'yes', False otherwise
    :raises: :class:`InputValidationException` if input was not provided, or id 'y' was provided instead of 'yes'
    """
    user_input = _prepare_input(user_input)
    if user_input == 'yes':
        return True
    elif user_input == 'y':
        raise InputValidationException('You must fully type "yes"')
    return False


def parse_with_func(func: Callable, user_input: str):
    user_input = _prepare_input(user_input)
    try:
        return func(user_input)
    except Exception as e:
        raise InputValidationException(f'Invalid input: {e}') from e


def parse_int(user_input: str) -> int:
    user_input = _prepare_input(user_input)
    try:
        return int(user_input)
    except ValueError:
        raise InputValidationException(f'Invalid input={user_input!r} - an integer is required') from None
    except Exception as e:
        raise InputValidationException(f'Invalid input={user_input!r} - an integer is required') from e


def _prepare_input(user_input: str):
    user_input = user_input.strip()
    if not user_input:
        raise InputValidationException('No input was provided.')
    return user_input
