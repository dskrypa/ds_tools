"""
Misc functions that did not fit anywhere else

:author: Doug Skrypa
"""

import functools
import re
import sys
from typing import Iterable
from warnings import warn

__all__ = [
    'num_suffix', 'PseudoJQ', 'bracket_dict_to_list', 'longest_repeating_subsequence', 'diamond', 'IntervalCoverage'
]


def num_suffix(num: int) -> str:
    """
    Returns the ordinal suffix (st, nd, rd, th) that should be used for the given base-10 integer.
    Handles both positive and negative integers.
    Correctly handles values such as 111th - 113rd with any value in the hundreds place.
    """
    warn('num_suffix is deprecated - use ds_tools.output.formatting.ordinal_suffix instead', DeprecationWarning)
    # While it may be slightly cleaner to use `num = abs(num)` and to store `tens = num % 100` before the if/elif
    # block, profiling revealed the below approach to be the fastest compared to approaches using those alternatives.
    if num < 0:
        num = -num
    ones = num % 10
    if not ones or ones > 3:
        return 'th'
    elif ones == 1:
        return 'th' if num % 100 == 11 else 'st'
    elif ones == 2:
        return 'th' if num % 100 == 12 else 'nd'
    else:  # ones == 3
        return 'th' if num % 100 == 13 else 'rd'


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
                subkeys = re.split(r'[\[\]]', k)
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


class IntervalCoverage:
    """
    Originally written for the zombit problem for Google's FooBar test; updated / cleaned up / expanded for use here.
    """
    def __init__(self, bits: int = 64, _is_sub: bool = False, intervals: Iterable[tuple[int, int]] = None):
        self.buckets = {}
        self.sub = None if _is_sub else IntervalCoverage(bits, True)
        self.bits = bits
        self.max_bucket_value = 2 ** bits - 1
        if intervals is not None:
            self.extend(intervals)

    def max_value(self) -> int:
        last_bucket = max(self.buckets) if self.buckets else 0
        bucket_max = last_bucket * self.bits
        if (sub := self.sub) is not None:
            return max(bucket_max, sub.max_value() * self.bits)
        return bucket_max

    @property
    def min(self) -> int:
        bits = self.bits
        if buckets := self.buckets:
            first = min(buckets)
            bucket = bin(buckets[first])[2:]
            bucket_min = (first * bits) + (len(bucket) - bucket.rindex('1') - 1)
        else:
            bucket_min = None
        if (sub := self.sub) is not None and (sub_min := sub.min) is not None:
            return sub_min * bits if bucket_min is None else min(bucket_min, sub_min * bits)
        return bucket_min

    @property
    def max(self) -> int:
        bits = self.bits
        if buckets := self.buckets:
            last = max(buckets)
            bucket = bin(buckets[last])[2:]
            bucket_max = (last * bits) + (len(bucket) - bucket.index('1') - 1)
        else:
            bucket_max = None
        if (sub := self.sub) is not None and (sub_max := sub.max) is not None:
            return sub_max * bits if bucket_max is None else max(bucket_max, sub_max * bits)
        return bucket_max

    def _iter_pages(self):
        mbv = bin(self.max_bucket_value)[2:]
        bucket = self.buckets.get
        has_sub = (sub := self.sub) is not None
        for b in range(self.max_value() // self.bits + 1):
            yield mbv if has_sub and sub[b] else bin(bucket(b, 0))[2:]

    def pformat(self) -> str:
        fmt = f'    {{:>{len(str(self.max_value() // self.bits))}d}}: {{:>0{self.bits}s}},'
        _buckets = '\n'.join(fmt.format(i, page) for i, page in enumerate(self._iter_pages()))
        info = f'min={self.min}, max={self.max}, filled={self.filled()}, contents'
        return f'\n<{self.__class__.__name__}({info}:\n{_buckets}\n)>'

    def pprint(self):
        print(self.pformat())

    def filled(self) -> int:
        total = 0
        bits = self.bits
        if (sub := self.sub) is not None:
            total += sub.filled() * bits

        try:
            # According to profiling, this is technically slower than a loop with `total += v.bit_count()`,
            # but this is simpler for version EAFP
            return sum(map(int.bit_count, self.buckets.values()), total)
        except AttributeError:  # Python version < 3.10
            max_value = self.max_bucket_value
            # If int.bit_count did not exist in 3.10, this would be faster without the max_value check, but the check
            # makes this significantly faster for 3.9 and below
            return total + sum(bits if v == max_value else bin(v).count('1') for v in self.buckets.values())

    def __getitem__(self, item: int) -> bool:
        index = item // self.bits
        if (sub := self.sub) is not None and sub[index]:
            return True
        elif index not in self.buckets:
            return False
        return self.buckets[index] & (1 << (item % self.bits)) != 0

    def __contains__(self, span) -> bool:
        try:
            start, stop = map(int, span)
        except (ValueError, TypeError):
            raise ValueError(f'Expected a span of (start, stop) integers')
        return all(self[i] for i in range(start, stop))

    def extend(self, intervals: Iterable[tuple[int, int]]):
        for start, stop in intervals:
            self.add(start, stop)

    def add(self, start: int, stop: int):
        bits = self.bits
        max_value = self.max_bucket_value
        start_i = start // bits
        stop_i = stop // bits
        smb = start % bits  # Start move bits
        if stop_i - start_i == 0:  # Insert full delta if all are in the same bucket
            delta = stop - start
            self._insert(start_i, max_value >> (bits - delta) << smb)
        else:
            self._insert(start_i, max_value >> smb << smb)
            emb = bits - (stop % bits)  # end move bits
            self._insert(stop_i, max_value >> emb)
            sub_first = start_i + 1
            if (sub := self.sub) is not None:
                sub_last = stop_i - 1
                sub.add(sub_first, stop_i)
                # Remove duplicate pages
                self.buckets = {k: v for k, v in self.buckets.items() if k < sub_first or k > sub_last and v}
            else:
                for i in range(sub_first, stop_i):
                    self.buckets[i] = max_value

    def _insert(self, index: int, mask: int):
        masked = self.buckets.get(index, 0) | mask
        if (sub := self.sub) is not None:
            if sub[index]:
                self.buckets.pop(index, None)  # Ensure duplicate bucket doesn't exist
                return
            max_value = self.max_bucket_value
            if masked == max_value:  # The bucket is full...
                sub._insert(index // max_value, 1 << (index % max_value))  # ...so it can be compressed
                self.buckets.pop(index, None)
                return
        if masked:
            self.buckets[index] = masked
