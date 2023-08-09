#!/usr/bin/env python

from unittest import TestCase, main

from ds_tools.caching.decorators import register_cached_property_class, unregister_cached_property_class
from ds_tools.caching.decorators import ClearableCachedPropertyMixin
from ds_tools.core.config import ConfigItem, ConfigSection, NestedSection
from ds_tools.core.config import MissingConfigItemError, InvalidConfigError, ConfigTypeError


class ConfigTest(TestCase):
    # Note: noqa comments on assertIn / assertNotIn checks are present
    # because PyCharm doesn't seem to understand __contains__ well

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
        self.assertNotIn('bar.baz', config)  # noqa
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
        self.assertIn('foo.bar', config)  # noqa
        self.assertNotIn('foo.baz', config)  # noqa
        self.assertEqual('abc', config['foo.bar'])
        self.assertIsNone(config['foo.baz'])
        config['foo.baz'] = 456
        self.assertEqual(456, config['foo.baz'])
        del config['foo.baz']
        self.assertIsNone(config['foo.baz'])

    def test_permissive_getitem_with_delim(self):
        class FooConfig(ConfigSection):
            bar = ConfigItem(123)

        class Config(ConfigSection, key_delimiter='.', strict=False):
            foo: FooConfig = NestedSection(FooConfig)

        self.assertNotIn('foo.bar', Config())  # noqa
        self.assertNotIn('foo.bar', Config({'foo': {}}))  # noqa
        self.assertNotIn('abc.123', Config())  # noqa
        self.assertIn('abc.xyz', Config({'abc': {'xyz': 1}}))  # noqa

        abc_int = Config({'abc': 123})
        self.assertNotIn('abc.123', abc_int)  # noqa
        with self.assertRaises(KeyError):
            abc_int['abc.123']  # noqa
        with self.assertRaises(KeyError):
            abc_int['abc.123'] = 456
        with self.assertRaises(KeyError):
            del abc_int['abc.123']

    def test_permissive_getitem_with_no_delim(self):
        class Config(ConfigSection, strict=False):
            foo = ConfigItem(123)

        config = Config({'foo.bar': 456})
        self.assertEqual(123, config.foo)
        self.assertEqual(456, config['foo.bar'])
        with self.assertRaises(KeyError):
            config['abc']  # noqa
        with self.assertRaises(KeyError):
            del config['abc']

    def test_bad_key_strict(self):
        class Config(ConfigSection):
            foo = ConfigItem(123, type=int)

        with self.assertRaisesRegex(InvalidConfigError, 'Invalid configuration - unsupported options:'):
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
        self.assertIn('foo', config)  # noqa
        self.assertIn('bar', config)  # noqa
        self.assertNotIn('baz', config)  # noqa

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

    def test_extension_override(self):
        class AConfig(ConfigSection):
            foo = ConfigItem(123)

        class BConfig(AConfig):
            foo = ConfigItem(456)

        class CConfig(BConfig):
            pass

        config = BConfig()
        self.assertIsInstance(config, AConfig)
        self.assertEqual(456, config.foo)
        self.assertEqual(123, AConfig().foo)
        self.assertEqual(456, CConfig().foo)

    def test_filter(self):
        class Config(ConfigSection):
            foo = ConfigItem()

        self.assertEqual({}, Config.filter({'bar': 123}))
        self.assertEqual({'foo': 456}, Config.filter({'foo': 456, 'bar': 123}))
        self.assertEqual({'foo': 456}, Config.filter({'foo': 456, 'bar': 123}))
        self.assertEqual({'foo': 456}, Config.filter({'bar': 123}, {'foo': 456}))
        self.assertEqual({}, Config.filter({'foo': 456}, exclude={'foo'}))
        self.assertEqual({}, Config.filter({}))

    def test_filter_truthy(self):
        class Config(ConfigSection):
            foo = ConfigItem()
            bar = ConfigItem()

        self.assertEqual({}, Config.filter({'foo': None}, {'bar': 0}, truthy=True))
        self.assertEqual({'bar': 1}, Config.filter({'foo': None}, {'bar': 1}, truthy=True))
        self.assertEqual({'bar': 1, 'foo': 'a'}, Config.filter({'foo': 'a'}, {'bar': 1}, truthy=True))
        self.assertEqual({'bar': 1, 'foo': 'a'}, Config.filter({'foo': 'a', 'bar': 1}, truthy=True))
        self.assertEqual({'bar': 1}, Config.filter({'foo': 'a', 'bar': 1}, truthy=True, exclude={'foo'}))

    def test_unflatten(self):
        class BConfig(ConfigSection):
            c = ConfigItem(2)
            d = ConfigItem(3)

        class AConfig(ConfigSection):
            a = ConfigItem(1)
            b = NestedSection(BConfig)

        self.assertEqual({'a': 3, 'b': {'c': 4}}, AConfig.filter({'a': 3, 'c': 4}, unflatten=True))
        self.assertEqual({'a': 3}, AConfig.filter({'a': 3, 'baz': None}, truthy=True, unflatten=True))
        self.assertEqual({'b': {'c': 4}}, AConfig.filter({'a': None, 'c': 4}, truthy=True, unflatten=True))
        self.assertEqual({'a': 3, 'b': {'c': 4}}, AConfig.filter({'a': 3, 'b': {'c': 4}}, unflatten=True))
        self.assertEqual(
            {'a': 3, 'b': {'c': 4, 'd': 5}}, AConfig.filter({'a': 3, 'b': {'c': 4}, 'd': 5}, unflatten=True)
        )
        self.assertEqual({'a': 3}, AConfig.filter({'a': 3, 'b': {'c': 4}, 'd': 5}, unflatten=True, exclude={'b'}))

    def test_update_known(self):
        class Config(ConfigSection):
            foo = ConfigItem()

        config = Config()
        self.assertEqual({}, config.__dict__)
        config.update_known({'bar': 123})
        self.assertEqual({}, config.__dict__)
        config.update_known(foo=456, bar=789)
        self.assertEqual({'foo': 456}, config.__dict__)
        config.update_known(Config(foo=987))
        self.assertEqual({'foo': 987}, config.__dict__)

    def test_as_dict_no_defaults(self):
        class Config(ConfigSection):
            a = ConfigItem(1)
            b = ConfigItem(2)

        config = Config({'a': 10})
        self.assertEqual({'a': 10, 'b': 2}, config.as_dict())
        self.assertEqual({'a': 10}, config.as_dict(include_defaults=False))

    def test_nested_update_known(self):
        class BConfig(ConfigSection):
            c = ConfigItem(2)
            d = ConfigItem(3)

        class AConfig(ConfigSection):
            a = ConfigItem(1)
            b = NestedSection(BConfig)

        config = AConfig({'a': 10, 'b': {'c': 20}})
        self.assertEqual({'a': 10, 'b': {'c': 20, 'd': 3}}, config.as_dict())
        self.assertEqual({'a': 10}, config.as_dict(recursive=False))
        config.update_known({'b': {'d': 30, 'e': 40}, 'f': 50})
        self.assertEqual({'a': 10, 'b': {'c': 20, 'd': 30}}, config.as_dict())

    def test_nested_update_known_no_merge(self):
        class BConfig(ConfigSection):
            c = ConfigItem(2)
            d = ConfigItem(3)

        class AConfig(ConfigSection, merge_nested=False):
            a = ConfigItem(1)
            b = NestedSection(BConfig)

        config = AConfig({'a': 10, 'b': {'c': 20}})
        self.assertEqual({'a': 10, 'b': {'c': 20, 'd': 3}}, config.as_dict())
        config.update_known({'b': {'d': 30, 'e': 40}, 'f': 50})
        self.assertEqual({'a': 10, 'b': {'c': 2, 'd': 30}}, config.as_dict())

    def test_3_nested_update_known(self):
        class CConfig(ConfigSection):
            f = ConfigItem(5)
            g = ConfigItem(6)

        class BConfig(ConfigSection):
            c = NestedSection(CConfig)
            d = ConfigItem(3)
            e = ConfigItem(4)

        class AConfig(ConfigSection):
            a = ConfigItem(1)
            b = NestedSection(BConfig)

        config = AConfig({'a': 10, 'b': {'c': {'f': 50}, 'd': 30}})
        self.assertEqual({'a': 10, 'b': {'c': {'f': 50, 'g': 6}, 'd': 30, 'e': 4}}, config.as_dict())
        config.update_known({'b': {'c': {'g': 60, 'h': 70}, 'e': 40}, 'f': 500})
        self.assertEqual({'a': 10, 'b': {'c': {'f': 50, 'g': 60}, 'd': 30, 'e': 40}}, config.as_dict())
        with self.assertRaisesRegex(ConfigTypeError, "Invalid configuration for key='b'.'c' - expected"):
            AConfig({'b': {'c': ['x', 'y', 'z']}})

    def test_3_nested_update_known_no_merge(self):
        class CConfig(ConfigSection):
            f = ConfigItem(5)
            g = ConfigItem(6)

        class BConfig(ConfigSection, merge_nested=False):
            c = NestedSection(CConfig)
            d = ConfigItem(3)
            e = ConfigItem(4)

        class AConfig(ConfigSection, merge_nested=False):
            a = ConfigItem(1)
            b = NestedSection(BConfig)

        config = AConfig({'a': 10, 'b': {'c': {'f': 50}, 'd': 30}})
        self.assertEqual({'a': 10, 'b': {'c': {'f': 50, 'g': 6}, 'd': 30, 'e': 4}}, config.as_dict())
        config.update_known({'b': {'c': {'g': 60, 'h': 70}, 'e': 40}, 'f': 500})
        self.assertEqual({'a': 10, 'b': {'c': {'f': 5, 'g': 60}, 'd': 3, 'e': 40}}, config.as_dict())
        with self.assertRaisesRegex(ConfigTypeError, "Invalid configuration for key='b'.'c' - expected"):
            AConfig({'b': {'c': ['x', 'y', 'z']}})

    def test_bad_nested_section_value(self):
        for strict in (True, False):
            with self.subTest(strict=strict):
                class BConfig(ConfigSection, strict=strict):
                    c = ConfigItem(None)

                class AConfig(ConfigSection):
                    b = NestedSection(BConfig)

                with self.assertRaisesRegex(ConfigTypeError, "Invalid configuration for key='b' - expected"):
                    AConfig({'b': ['x', 'y', 'z']})


if __name__ == '__main__':
    main(verbosity=2)
