#!/usr/bin/env python

from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import partial
from operator import attrgetter
from time import sleep, monotonic
from threading import RLock
from unittest import TestCase, main
from unittest.mock import Mock, MagicMock

from ds_tools.caching.decorate import cached, CachedFunc, LockingCachedFunc, CacheLockWarning, CacheKey


LockType = type(RLock())


class AssertRuntimeBelowThreshold:
    __slots__ = ('test_case', 'threshold', 'start')

    def __init__(self, test_case: TestCase, delay: float, threshold: float = None):
        self.test_case = test_case
        if threshold is None:
            threshold = 1.35 if delay < 0.1 else 1.125
        self.threshold = delay * threshold

    def __enter__(self):
        self.start = monotonic()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        elapsed = monotonic() - self.start
        self.test_case.assertLess(elapsed, self.threshold)


class IncrementingMultiplier:
    __slots__ = ('n', 'delay')

    def __init__(self, n: int = 0, delay: float = 0):
        self.n = n
        self.delay = delay

    def __call__(self, x: int) -> int:
        if self.delay:
            sleep(self.delay)
        self.n += 1
        return x * self.n


class PerKeyIncrementingMultiplier(IncrementingMultiplier):
    __slots__ = ('key_n_map',)

    def __init__(self, n: int = 0, delay: float = 0):
        super().__init__(n, delay)
        self.key_n_map = {}

    def __call__(self, x: int) -> int:
        if self.delay:
            sleep(self.delay)
        self.key_n_map[x] = n = self.key_n_map.get(x, self.n) + 1
        return x * n


class TestAssertionHelpers(TestCase):
    def test_assert_runtime_below_threshold(self):
        with self.assertRaises(AssertionError):
            with AssertRuntimeBelowThreshold(self, 0.01):
                sleep(0.02)


class TestCacheKey(TestCase):
    def test_not_equal_to_different_type(self):
        self.assertNotEqual(CacheKey(1), 1)


class TestCachedFunc(TestCase):
    # region Initialization

    def test_invalid_cache_type(self):
        with self.assertRaisesRegex(TypeError, 'Invalid type=.* for cache=.* with method=True - expected'):
            CachedFunc(Mock(), [], method=True)

    def test_auto_method_cache_converted_to_attrgetter(self):
        cf = CachedFunc(Mock(), 'cache_attr')
        self.assertIsInstance(cf.cache, attrgetter)
        self.assertTrue(cf.method)

    def test_auto_method_cache_as_attrgetter(self):
        cf = CachedFunc(Mock(), attrgetter('cache_attr'))
        self.assertIsInstance(cf.cache, attrgetter)
        self.assertTrue(cf.method)

    # endregion

    def test_cached_value_is_returned(self):
        for cls in (CachedFunc, LockingCachedFunc):
            with self.subTest(cls=cls):
                func = cls(IncrementingMultiplier())
                self.assertEqual(2, func(2))
                self.assertEqual(2, func(2))
                self.assertEqual(4, func.func(2))
                self.assertEqual(2, func(2))

    def test_separate_cached_values_are_returned(self):
        for cls in (CachedFunc, LockingCachedFunc):
            with self.subTest(cls=cls):
                func = cls(PerKeyIncrementingMultiplier())
                self.assertEqual(2, func(2))
                self.assertEqual(2, func(2))
                self.assertEqual(4, func.func(2))
                self.assertEqual(2, func(2))
                self.assertEqual(3, func(3))
                self.assertEqual(3, func(3))
                self.assertEqual(6, func.func(3))
                self.assertEqual(3, func(3))

    def test_method_no_cache(self):
        for cls in (CachedFunc, LockingCachedFunc):
            with self.subTest(cls=cls):
                kwargs = {'lock': lambda _: RLock()} if cls is LockingCachedFunc else {}
                func = cls(IncrementingMultiplier(), method=True, cache=lambda _: None, **kwargs)
                self.assertEqual(2, func(2))
                self.assertEqual(4, func(2))
                self.assertEqual(6, func(2))

    def test_pass_thru_key(self):
        for cls in (CachedFunc, LockingCachedFunc):
            with self.subTest(cls=cls):
                cache = {}
                func = cls(lambda x: x + 1, cache=cache, key=lambda y: y)
                func(1)
                self.assertEqual({1: 2}, cache)
                func(2)
                self.assertEqual({1: 2, 2: 3}, cache)

    def test_exception_not_cached(self):
        for cls in (CachedFunc, LockingCachedFunc):
            with self.subTest(cls=cls):
                func = cls(Mock(side_effect=(ValueError, 2, RuntimeError)))
                with self.assertRaises(ValueError):
                    func(1)
                self.assertEqual(2, func(1))
                self.assertEqual(2, func(1))

    def test_exception_cached(self):
        for cls in (CachedFunc, LockingCachedFunc):
            with self.subTest(cls=cls):
                func = cls(Mock(side_effect=(ValueError, 2, RuntimeError)), exc=True)
                with self.assertRaises(ValueError):
                    func(1)
                with self.assertRaises(ValueError):
                    func(1)

    def test_cached_class_method(self):
        class Foo:
            bar_calls = 0
            baz_calls = 0

            @cached()  # noqa
            @classmethod
            def bar(cls, n):
                cls.bar_calls += 1
                return n + 1

            @classmethod
            @cached()
            def baz(cls, n):
                cls.baz_calls += 1
                return n + 2

        self.assertEqual(2, Foo.bar(1))
        self.assertEqual(2, Foo.bar(1))
        self.assertEqual(1, Foo.bar_calls)
        self.assertEqual(3, Foo.bar(2))
        self.assertEqual(2, Foo.bar_calls)

        self.assertEqual(3, Foo.baz(1))
        self.assertEqual(3, Foo.baz(1))
        self.assertEqual(1, Foo.baz_calls)
        self.assertEqual(4, Foo.baz(2))
        self.assertEqual(2, Foo.baz_calls)

    def test_caching_optional(self):
        for cls in (cached(optional=True), partial(LockingCachedFunc, optional=True)):
            with self.subTest(cls=cls):
                func = cls(PerKeyIncrementingMultiplier())
                self.assertEqual(2, func(2))
                self.assertEqual(2, func(2))
                self.assertEqual(4, func(2, use_cached=False))
                self.assertEqual(4, func(2))

                self.assertEqual(3, func(3))
                self.assertEqual(3, func(3))
                self.assertEqual(6, func(3, use_cached=False))
                self.assertEqual(6, func(3))


class TestLockingCachedFunc(TestCase):
    # region Initialization

    def test_auto_method_lock_converted_to_attrgetter(self):
        cf = LockingCachedFunc(Mock(), 'cache_attr', lock='bar')
        self.assertIsInstance(cf.lock, attrgetter)
        self.assertTrue(cf.method)

    def test_auto_method_cache_as_attrgetter(self):
        cf = LockingCachedFunc(Mock(), 'cache_attr', lock=attrgetter('bar'))
        self.assertIsInstance(cf.lock, attrgetter)
        self.assertTrue(cf.method)

    def test_default_lock(self):
        self.assertIsInstance(LockingCachedFunc(Mock()).lock, LockType)

    def test_explicit_lock(self):
        lock = RLock()
        self.assertIs(lock, LockingCachedFunc(Mock(), lock=lock).lock)

    # endregion

    def test_concurrent_call_with_same_args_waits_for_lock(self):
        delay = 0.05
        func = LockingCachedFunc(IncrementingMultiplier(delay=delay))
        with ThreadPoolExecutor(max_workers=3) as pool, AssertRuntimeBelowThreshold(self, delay):
            for future in as_completed(pool.submit(func, 2) for _ in range(3)):
                self.assertEqual(2, future.result())

    def test_concurrent_calls_for_different_args_do_not_block_each_other(self):
        delay = 0.05
        func = LockingCachedFunc(PerKeyIncrementingMultiplier(delay=delay))
        with ThreadPoolExecutor(max_workers=4) as pool, AssertRuntimeBelowThreshold(self, delay):
            futures = {pool.submit(func, n): n for n in (2, 2, 3, 3)}
            for future in as_completed(futures):
                self.assertEqual(futures[future], future.result())

    def test_shared_lock_warns_and_is_used(self):
        delay = 0.05
        with self.assertWarns(CacheLockWarning):
            class Foo:
                def __init__(self):
                    self.cache = {}

                @cached('cache', lock=RLock(), key_lock=False)  # noqa
                def bar(self, baz):
                    sleep(delay)
                    return baz + 1

        cf = Foo.bar
        self.assertIsInstance(cf, LockingCachedFunc)
        self.assertTrue(cf.method)
        self.assertIsInstance(cf.cache, attrgetter)

        instances = [Foo(), Foo()]
        with ThreadPoolExecutor(max_workers=2) as pool, AssertRuntimeBelowThreshold(self, delay):
            for future in as_completed(pool.submit(foo.bar, 2) for foo in instances):
                self.assertEqual(3, future.result())

        self.assertEqual([1, 1], [len(foo.cache) for foo in instances])

    def test_methods_use_separate_default_locks(self):
        class Foo:
            @cached(MagicMock(), method=True, lock=True)  # noqa
            def bar(self, n):
                return n + 1

            @cached(MagicMock(), method=True, lock=True)
            def baz(self, n):
                return n + 2

        foo = Foo()
        self.assertEqual({}, foo.__dict__)
        foo.bar(1)
        self.assertIsInstance(foo.__dict__['_cached__bar_lock'], LockType)
        foo.baz(1)
        self.assertIsInstance(foo.__dict__['_cached__baz_lock'], LockType)


if __name__ == '__main__':
    main(verbosity=2)
