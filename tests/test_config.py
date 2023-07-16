#!/usr/bin/env python

from unittest import TestCase, main

from ds_tools.core.config import ConfigItem, ConfigSection, NestedSection, MissingConfigItemError, InvalidConfigError


class ConfigTest(TestCase):
    def test_nested_config(self):
        class BarConfig(ConfigSection):
            baz = ConfigItem(None)

        class AConfig(ConfigSection):
            foo = ConfigItem(123, type=int)
            bar = NestedSection(BarConfig)

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
        config = AConfig({'foo': 456, 'bar': {'baz': 'abc'}})
        self.assertEqual(456, config.foo)
        self.assertEqual('abc', config.bar.baz)
        self.assertEqual('abc', BConfig({'boz': 'abc'}).boz)

    def test_bad_key(self):
        class Config(ConfigSection):
            foo = ConfigItem(123, type=int)

        with self.assertRaises(InvalidConfigError):
            Config({'bar': 1})
        with self.assertRaises(InvalidConfigError):
            Config({'foo': 1}, bar=2)
        with self.assertRaises(InvalidConfigError):
            Config(bar=2)

    def test_missing_value(self):
        class Config(ConfigSection):
            foo = ConfigItem()  # No default

        with self.assertRaises(MissingConfigItemError):
            _ = Config().foo


if __name__ == '__main__':
    main(verbosity=2)
