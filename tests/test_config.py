#!/usr/bin/env python

from unittest import TestCase, main

from ds_tools.caching.decorators import register_cached_property_class, unregister_cached_property_class
from ds_tools.caching.decorators import ClearableCachedPropertyMixin
from ds_tools.core.config import ConfigItem, ConfigSection, NestedSection, MissingConfigItemError, InvalidConfigError


class ConfigTest(TestCase):
    @classmethod
    def setUpClass(cls):
        register_cached_property_class(ConfigItem)

    @classmethod
    def tearDownClass(cls):
        unregister_cached_property_class(ConfigItem)

    def test_repr(self):
        class Config(ConfigSection):
            foo = ConfigItem(123)

        self.assertIn('123,', repr(Config.foo))

    def test_update_empty(self):
        class Config(ConfigSection):
            foo = ConfigItem(123)

        config = Config({'foo': 456})
        config.update()
        self.assertEqual(456, config.foo)

    def test_nested_config(self):
        class BarConfig(ConfigSection):
            baz = ConfigItem(None)

        class AConfig(ConfigSection):
            foo = ConfigItem(123, type=int)
            bar: BarConfig = NestedSection(BarConfig)

        class BConfig(AConfig):
            boz = ConfigItem(None)

        self.assertNotIn('boz', AConfig._config_items_)
        self.assertSetEqual({'foo', 'bar', 'boz'}, set(BConfig._config_items_))
        self.assertIsInstance(AConfig().bar, BarConfig)
        self.assertIsInstance(BConfig().bar, BarConfig)
        self.assertIsNone(AConfig().bar.baz)
        self.assertIsNone(AConfig({'bar': {}}).bar.baz)
        self.assertIsNone(BConfig({'foo': 456}).bar.baz)
        self.assertEqual(123, AConfig().foo)
        self.assertEqual(123, BConfig().foo)
        self.assertEqual('abc', BConfig({'boz': 'abc'}).boz)

        config = AConfig({'foo': 456, 'bar': {'baz': 'abc'}})
        self.assertEqual(456, config.foo)
        self.assertEqual('abc', config.bar.baz)
        self.assertEqual('abc', config.bar['baz'])
        self.assertEqual('abc', config['bar']['baz'])
        self.assertNotIn('bar.baz', config)  # noqa  # PyCharm doesn't seem to understand __contains__
        with self.assertRaises(KeyError):  # delimiter-based access is not enabled by default
            config['bar.baz']  # noqa
        with self.assertRaises(KeyError):
            config['bar.baz'] = 123
        with self.assertRaises(KeyError):
            del config['bar.baz']

    def test_nested_config_item_handling(self):
        class FooConfig(ConfigSection):
            bar = ConfigItem(123)
            baz = ConfigItem(None)

        class Config(ConfigSection, key_delimiter='.'):
            foo: FooConfig = NestedSection(FooConfig)

        config = Config({'foo': {'bar': 'abc'}})
        self.assertIn('foo.bar', config)  # noqa  # PyCharm doesn't seem to understand __contains__
        self.assertNotIn('foo.baz', config)  # noqa  # PyCharm doesn't seem to understand __contains__
        self.assertEqual('abc', config['foo.bar'])
        self.assertIsNone(config['foo.baz'])
        config['foo.baz'] = 456
        self.assertEqual(456, config['foo.baz'])
        del config['foo.baz']
        self.assertIsNone(config['foo.baz'])

    def test_bad_key_strict(self):
        class Config(ConfigSection):
            foo = ConfigItem(123, type=int)

        with self.assertRaises(InvalidConfigError):
            Config({'bar': 1})
        with self.assertRaises(InvalidConfigError):
            Config({'foo': 1}, bar=2)
        with self.assertRaises(InvalidConfigError):
            Config(bar=2)
        with self.assertRaises(InvalidConfigError):
            Config().update(bar=2)
        with self.assertRaises(InvalidConfigError):
            Config().update({'foo': 1, 'bar': 2})
        with self.assertRaises(KeyError):
            Config()['bar']  # noqa
        with self.assertRaises(KeyError):
            Config()['bar'] = 123

    def test_bad_key_permissive(self):
        class Config(ConfigSection, strict=False):
            foo = ConfigItem(123)

        self.assertEqual(1, Config({'bar': 1}).bar)  # noqa
        self.assertEqual(2, Config({'foo': 1}, bar=2).bar)  # noqa

        config = Config({'foo': 1})
        config.update(bar=1)
        self.assertEqual(1, config.foo)
        self.assertEqual(1, config.bar)  # noqa
        self.assertIn('foo', config)  # noqa  # PyCharm doesn't seem to understand __contains__
        self.assertNotIn('bar', config)  # noqa  # PyCharm doesn't seem to understand __contains__

    def test_missing_value(self):
        class Config(ConfigSection):
            foo = ConfigItem()  # No default

        with self.assertRaises(MissingConfigItemError):
            _ = Config().foo

    def test_clear_cached_value(self):
        class Config(ClearableCachedPropertyMixin, ConfigSection):
            foo = ConfigItem(123)

        config = Config(foo=456)
        self.assertEqual(456, config.foo)
        config.clear_cached_properties()
        self.assertEqual(123, config.foo)

    def test_delete_value(self):
        class Config(ConfigSection):
            foo = ConfigItem(123)

        config = Config(foo=456)
        self.assertEqual(456, config.foo)
        del config.foo
        self.assertEqual(123, config.foo)
        with self.assertRaises(AttributeError):
            del config.foo

    def test_merge_nested_true(self):
        class XConfig(ConfigSection):
            y = ConfigItem(None)
            z = ConfigItem(None)

        class Config(ConfigSection):
            a: int = ConfigItem(123, type=int)
            x: XConfig = NestedSection(XConfig)

        config = Config({'a': 456, 'x': {'y': 1}})
        self.assertEqual(456, config.a)
        self.assertEqual(1, config.x.y)
        self.assertIsNone(config.x.z)
        config.update({'a': 789, 'x': {'z': 2}})
        self.assertEqual(789, config.a)
        self.assertEqual(1, config.x.y)
        self.assertEqual(2, config.x.z)

    def test_merge_nested_false(self):
        class XConfig(ConfigSection):
            y = ConfigItem(None)
            z = ConfigItem(None)

        class Config(ConfigSection, merge_nested=False):
            a: int = ConfigItem(123, type=int)
            x: XConfig = NestedSection(XConfig)

        config = Config({'a': 456, 'x': {'y': 1}})
        self.assertEqual(456, config.a)
        self.assertEqual(1, config.x.y)
        self.assertIsNone(config.x.z)
        config.update({'a': 789, 'x': {'z': 2}})
        self.assertEqual(789, config.a)
        self.assertIsNone(config.x.y)
        self.assertEqual(2, config.x.z)

    def test_merge_nested_inherited(self):
        class AConfig(ConfigSection, merge_nested=False):
            foo = ConfigItem(123)

        class BConfig(AConfig):
            bar = ConfigItem(456)

        self.assertFalse(AConfig._merge_nested_sections_)
        self.assertFalse(BConfig._merge_nested_sections_)

    def test_strict_inherited(self):
        class AConfig(ConfigSection, strict=False):
            foo = ConfigItem(123)

        class BConfig(AConfig):
            bar = ConfigItem(456)

        self.assertFalse(AConfig._strict_config_keys_)
        self.assertFalse(BConfig._strict_config_keys_)

    def test_key_delim_inherited(self):
        class AConfig(ConfigSection, key_delimiter='~'):
            foo = ConfigItem(123)

        class BConfig(AConfig):
            bar = ConfigItem(456)

        self.assertEqual('~', AConfig._config_key_delimiter_)
        self.assertEqual('~', BConfig._config_key_delimiter_)


if __name__ == '__main__':
    main(verbosity=2)
