"""
Utilities to provide grammatically correct output.

:author: Doug Skrypa
"""

__all__ = ['a_or_an']


def a_or_an(noun: str) -> str:
    if not noun:
        return 'a'
    return 'an' if noun[0] in 'aeiou' else 'a'
