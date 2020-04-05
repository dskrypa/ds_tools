"""
Misc functions that did not fit anywhere else

:author: Doug Skrypa
"""

import functools
import re
import sys

__all__ = ['num_suffix', 'PseudoJQ', 'bracket_dict_to_list', 'longest_repeating_subsequence', 'diamond']


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


class PseudoJQ:
    ALL = (None,)

    def __init__(self, key_str, printer=None):
        if not key_str.startswith('.'):
            raise ValueError('Invalid key string: {}'.format(key_str))
        try:
            self.keys = self.parse_keys(key_str)
        except Exception as e:
            if isinstance(e, KeyboardInterrupt):
                raise e
            raise ValueError('Invalid key string: {}'.format(key_str))
        self.p = printer

    @classmethod
    def extract(cls, content, key_str):
        return PseudoJQ(key_str)._extract(content, -1)

    @classmethod
    def parse_keys(cls, key_str):
        key_list = key_str.split('.')
        keys = []
        for k in key_list[1:]:
            if '[' in k:
                subkeys = re.split('[\[\]]', k)
                keys.append(subkeys.pop(0))
                if subkeys == ['', '']:
                    keys.append(cls.ALL)
                else:
                    sk_list = []
                    subkeys = subkeys[0].split(',')
                    for sk in subkeys:
                        if '-' in sk:
                            a, b = map(int, sk.split('-'))
                            sk_list.extend(range(a, b + 1))
                        else:
                            sk_list.append(int(sk))
                    keys.append(sk_list)
            else:
                keys.append(k)
        return keys

    def _extract(self, content, k):
        k += 1
        if k > len(self.keys) - 1:
            return content

        key = self.keys[k]
        if key is self.ALL:
            return (self._extract(i, k) for i in content)
        elif isinstance(key, list):
            try:
                return (self._extract(content[i], k) for i in key)
            except IndexError:
                raise ValueError('One or more list indexes out of range: {}'.format(key))
        else:
            return self._extract(content[key], k)

    def extract_and_print(self, content):
        self.p.pprint(self._extract(content, -1))


def bracket_dict_to_list(obj):
    """
    Translates nested dicts with keys being list indexes surrounded by brackets to lists.  This was written to handle
    strangely printed yaml content encountered in the wild where lists were formatted like this.

    Example:
    'some_key_to_a_list':
       - '[1]': value
       - '[2]': value

    Translated to json, that's
    {'some_key_to_a_list': [
        {'[1]': value},
        {'[2]': value}
    ]}

    Expected:
    'some_key_to_a_list':
       - value
       - value
    """
    if isinstance(obj, dict):
        if len(obj) < 1:
            return obj
        return {k: bracket_dict_to_list(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        if len(obj) < 1:
            return obj
        if functools.reduce(lambda a, b: a and b, [isinstance(v, dict) and (len(v) == 1) for v in obj]):
            if functools.reduce(lambda a, b: a and b, [obj[i].keys()[0] == '[{}]'.format(i) for i in range(len(obj))]):
                return [v.values()[0] for v in obj]
        return [bracket_dict_to_list(v) for v in obj]
    else:
        return obj


def longest_repeating_subsequence(seq):
    n = len(seq)
    lcsre = [[0 for x in range(n + 1)] for y in range(n + 1)]

    res = type(seq)()
    res_length = 0

    # building table in bottom-up manner
    index = 0
    for i in range(1, n + 1):
        for j in range(i + 1, n + 1):
            # (j-i) > LCSRe[i-1][j-1] to remove overlapping
            if seq[i - 1] == seq[j - 1] and lcsre[i - 1][j - 1] < (j - i):
                lcsre[i][j] = lcsre[i - 1][j - 1] + 1
                # updating maximum length of the subsequence and updating the finishing index of the suffix
                if lcsre[i][j] > res_length:
                    res_length = lcsre[i][j]
                    index = max(i, index)
            else:
                lcsre[i][j] = 0

    # If we have non-empty result, then insert all elements from first element to last element of the sequence
    if res_length > 0:
        for i in range(index - res_length + 1, index + 1):
            res = res + seq[i - 1]
    return res


def diamond():
    """
    Imitates the <> diamond operator from Perl.

    Note: On Windows, EOF = [ctrl]+[z] (followed by [enter])

    Example usage::\n
        for line in diamond():
            print(line)

    :return: Generator that yields lines (str) from stdin or the files with the names in sys.argv
    """
    nlstrip = lambda s: s.rstrip('\n')

    if len(sys.argv) == 1:
        yield from map(nlstrip, sys.stdin.readlines())
    else:
        for file in sys.argv[1:]:
            if file == '-':
                yield from map(nlstrip, sys.stdin.readlines())
            else:
                with open(file, 'r') as f:
                    yield from map(nlstrip, f.readlines())
