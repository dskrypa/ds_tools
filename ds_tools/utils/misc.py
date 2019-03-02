"""
Misc functions that did not fit anywhere else

:author: Doug Skrypa
"""

__all__ = ['num_suffix']


def num_suffix(num):
    if 3 < num < 21:
        return 'th'
    ones_place = str(num)[-1:]
    if ones_place == '1':
        return 'st'
    elif ones_place == '2':
        return 'nd'
    elif ones_place == '3':
        return 'rd'
    return 'th'
