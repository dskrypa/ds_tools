#!/usr/bin/env python

import logging
import sys
import unittest
from functools import cached_property
from itertools import count
from pathlib import Path

sys.path.append(Path(__file__).parents[1].as_posix())
from ds_tools.caching.mixins import ClearableCachedPropertyMixin, ClearableCachedProperty, DictAttrProperty

log = logging.getLogger(__name__)


class Descriptor0:
    _counter = count()

    def __init__(self):
        self.name = f'{self.__class__.__name__}#{next(self._counter)}'
        self.n = 0
        self.get_calls = 0

    def __get__(self, obj, owner):
        if obj is None:
            return self
        self.get_calls += 1
        try:
            value = obj.__dict__[self.name]
        except KeyError:
            self.n += 1
            value = obj.__dict__[self.name] = self.n
        return value


class Descriptor1(Descriptor0, ClearableCachedProperty):
    _set_name = True


class Descriptor2(Descriptor0):
    _set_name = True            # No effect because this descriptor does not extend ClearableCachedProperty

# noinspection PyUnresolvedReferences
ClearableCachedProperty.register(Descriptor2)


class Descriptor3(Descriptor0, ClearableCachedProperty):
    # Doesn't really cache because of the way Descriptor0 was implemented (this is intentional for test purposes)
    pass


class ExampleClass(ClearableCachedPropertyMixin):
    foo = DictAttrProperty('bar', 'baz')
    d1 = Descriptor1()
    d2 = Descriptor2()
    d3 = Descriptor3()

    def __init__(self):
        self.n = 0
        self.bar = {'baz': 1}

    @cached_property
    def counter(self):
        self.n += 1
        return self.n


class CachedPropertyTest(unittest.TestCase):
    def test_names(self):
        self.assertEqual(ExampleClass.d1.name, 'd1')
        self.assertEqual(ExampleClass.d2.name, 'Descriptor2#1')
        self.assertEqual(ExampleClass.d3.name, 'Descriptor3#2')

    def test_dict_attr_property_doc(self):
        expected = (
            'A :class:`DictAttrProperty<ds_tools.caching.mixins.DictAttrProperty>` that references this ExampleClass'
            " instance's bar['baz']"
        )
        self.assertEqual(ExampleClass.foo.__doc__, expected)

    def test_dict_attr_property_cached(self):
        obj = ExampleClass()
        self.assertEqual(obj.foo, 1)
        obj.bar['baz'] = 2
        self.assertEqual(obj.foo, 1)

    def test_dict_attr_property_reset(self):
        obj = ExampleClass()
        self.assertEqual(obj.foo, 1)
        obj.bar['baz'] = 2
        obj.clear_cached_properties()
        self.assertEqual(obj.foo, 2)

    def test_cached_property_cached(self):
        obj = ExampleClass()
        self.assertEqual(obj.counter, 1)
        self.assertEqual(obj.counter, 1)
        obj.n = 2
        self.assertEqual(obj.counter, 1)

    def test_cached_property_reset(self):
        obj = ExampleClass()
        self.assertEqual(obj.counter, 1)
        obj.clear_cached_properties()
        self.assertEqual(obj.counter, 2)

    def test_inherited_ccp(self):
        orig_n, orig_calls = ExampleClass.d1.n, ExampleClass.d1.get_calls
        obj = ExampleClass()
        self.assertEqual(obj.d1, orig_n + 1)
        self.assertEqual(obj.d1, orig_n + 1)
        self.assertEqual(ExampleClass.d1.get_calls, orig_calls + 1)
        obj.clear_cached_properties()
        self.assertEqual(obj.d1, orig_n + 2)
        self.assertEqual(ExampleClass.d1.get_calls, orig_calls + 2)

    def test_registered_ccp(self):
        orig_n, orig_calls = ExampleClass.d2.n, ExampleClass.d2.get_calls
        obj = ExampleClass()
        self.assertEqual(obj.d2, orig_n + 1)
        self.assertEqual(obj.d2, orig_n + 1)
        self.assertEqual(ExampleClass.d2.get_calls, orig_calls + 2)
        obj.clear_cached_properties()           # Has no effect because it uses the attr name, and because this
        self.assertEqual(obj.d2, orig_n + 1)    # descriptor was only registered, it didn't get __set_name__
        self.assertEqual(ExampleClass.d2.get_calls, orig_calls + 3)

    def test_no_name_ccp(self):
        orig_n, orig_calls = ExampleClass.d3.n, ExampleClass.d3.get_calls
        obj = ExampleClass()
        self.assertEqual(obj.d3, orig_n + 1)
        self.assertEqual(obj.d3, orig_n + 1)
        self.assertEqual(ExampleClass.d3.get_calls, orig_calls + 2)
        obj.clear_cached_properties()
        self.assertEqual(obj.d3, orig_n + 1)
        self.assertEqual(ExampleClass.d3.get_calls, orig_calls + 3)


if __name__ == '__main__':
    try:
        unittest.main(warnings='ignore', verbosity=2, exit=False)
    except KeyboardInterrupt:
        print()
