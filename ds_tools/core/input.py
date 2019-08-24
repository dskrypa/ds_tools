"""
Input Handling

:author: Doug Skrypa
"""

import logging
from numbers import Number

import yaml

from .exceptions import InputValidationException

__all__ = ['get_input', 'parse_yes_no', 'parse_full_yes_no', 'parse_bool']
log = logging.getLogger(__name__)


class _NotSet:
    pass


def parse_bool(value):
    original = value
    if isinstance(value, bool):
        return value
    value = yaml.safe_load(value)           # Handles 0/1/true/True/TRUE/false/False/FALSE
    if isinstance(value, (Number, bool)):
        return bool(value)
    elif isinstance(value, str):
        value = value.lower()
        if value in ('t', 'y', 'yes'):
            return True
        elif value in ('f', 'n', 'no'):
            return False
    # ValueError works with argparse to provide a useful error message
    raise ValueError('Unable to parse voolean value from input: {!r}'.format(original))


def parse_yes_no(user_input):
    """
    Case-insensitive Yes/No input parser

    :param str user_input: Raw user input
    :return bool: True if the provided input started with Y, False if it started with N
    :raises: :class:`InputValidationException` if input did not start with a Y or N
    """
    user_input = user_input.strip()
    try:
        first_char = user_input[0].upper()
    except IndexError as e:
        raise InputValidationException('No input was provided') from e

    if first_char in ('Y', 'N'):
        return first_char == 'Y'
    raise InputValidationException('Expected "yes"/"y" or "no"/"n"')


def parse_full_yes_no(user_input):
    """
    Case-insensitive full Yes/No input parser

    :param str user_input: Raw user input
    :return bool: True is the provided input was 'yes', False otherwise
    :raises: :class:`InputValidationException` if input was not provided, or id 'y' was provided instead of 'yes'
    """
    user_input = user_input.strip().lower()
    if not user_input:
        raise InputValidationException('No input was provided.')

    if user_input == 'yes':
        return True
    elif user_input == 'y':
        raise InputValidationException('You must fully type "yes"')
    return False


def get_input(prompt, skip=False, retry=0, parser=parse_yes_no, *, default=_NotSet):
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
    suffix = ' ' if not prompt.endswith(' ') else ""

    while retry >=0:
        try:
            user_input = input(prompt + suffix)
        except EOFError as e:
            raise InputValidationException('Unable to read stdin (this is often caused by piped input)') from e

        try:
            return parser(user_input)
        except InputValidationException as e:
            retry -= 1
            if retry < 0:
                raise e
            log.error(e)
    raise InputValidationException('Unable to get user input')
