#!/usr/bin/env python

from functools import cached_property
from unittest import TestCase, main

from ds_tools.caching.mixins import ClearableCachedPropertyMixin, DictAttrProperty


class ExampleClass(ClearableCachedPropertyMixin):
    foo = DictAttrProperty('bar', 'baz')

    def __init__(self):
        self.n = 0
        self.bar = {'baz': 1}

    @cached_property
    def counter(self):
        self.n += 1
        return self.n


class DictAttrPropertyTest(TestCase):
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


if __name__ == '__main__':
    try:
        main(verbosity=2, exit=False)
    except KeyboardInterrupt:
        print()
