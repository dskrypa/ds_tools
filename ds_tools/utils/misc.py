"""
Misc functions that did not fit anywhere else

:author: Doug Skrypa
"""

import re
import functools

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


class MatchHolder:
    """
>>> import re
>>> match = MatchHolder()
>>> match
MatchHolder(None)
>>> if match(re.search("some (string)", "some string")):
...     dir(match)
...     match.groups()
...     match.span()
...
['__class__', '__copy__', '__deepcopy__', '__delattr__', '__dir__', '__doc__', '__eq__', '__format__', '__ge__', '__getattribute__', '__gt__', '__hash__', '__init__', '__le__', '__lt__', '__ne__', '__new__', '__reduce__', '__reduce_ex__', '__repr__', '__setattr__', '__sizeof__', '__str__', '__subclasshook__', 'end', 'endpos', 'expand', 'group', 'groupdict', 'groups', 'lastgroup', 'lastindex', 'pos', 're', 'regs', 'span', 'start', 'string']
('string',)
(0, 11)
>>> match
MatchHolder(<_sre.SRE_Match object; span=(0, 11), match='some string'>)
    """
    def __init__(self, match=None):
        self._match = match

    def __call__(self, match):
        self._match = match
        return self._match

    def __getattr__(self, attr):
        return getattr(self._match, attr)

    #following methods are optional / informational
    def __dir__(self):
        return dir(self._match)

    def __repr__(self):
        return "{}({})".format(type(self).__name__, repr(self._match))


class PseudoJQ:
    ALL = (None,)

    def __init__(self, key_str, printer=None):
        if not key_str.startswith("."):
            raise ValueError("Invalid key string: {}".format(key_str))
        try:
            self.keys = self.parse_keys(key_str)
        except Exception as e:
            if isinstance(e, KeyboardInterrupt):
                raise e
            raise ValueError("Invalid key string: {}".format(key_str))
        self.p = printer

    @classmethod
    def extract(cls, content, key_str):
        return PseudoJQ(key_str)._extract(content, -1)

    @classmethod
    def parse_keys(cls, key_str):
        key_list = key_str.split(".")
        keys = []
        for k in key_list[1:]:
            if "[" in k:
                subkeys = re.split("[\[\]]", k)
                keys.append(subkeys.pop(0))
                if subkeys == ["", ""]:
                    keys.append(cls.ALL)
                else:
                    sk_list = []
                    subkeys = subkeys[0].split(",")
                    for sk in subkeys:
                        if "-" in sk:
                            a, b = map(int, sk.split("-"))
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
                raise ValueError("One or more list indexes out of range: {}".format(key))
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
       - "[1]": value
       - "[2]": value

    Translated to json, that's
    {"some_key_to_a_list": [
        {"[1]": value},
        {"[2]": value}
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
            if functools.reduce(lambda a, b: a and b, [obj[i].keys()[0] == "[{}]".format(i) for i in range(len(obj))]):
                return [v.values()[0] for v in obj]
        return [bracket_dict_to_list(v) for v in obj]
    else:
        return obj