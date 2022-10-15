#!/usr/bin/env python

import functools as _functools
from abc import ABC, abstractmethod
from concurrent.futures import as_completed, ThreadPoolExecutor
from itertools import count
from time import sleep, monotonic
from unittest import TestCase, main
from unittest.mock import patch

from ds_tools.caching.decorators import ClearableCachedPropertyMixin, ClearableCachedProperty, cached_property
from ds_tools.caching.decorators import get_cached_property_names, CachedProperty

SLEEP_TIME = 0.05


class TestError(Exception):
    pass


class ConcurrentAccessBase(ABC):
    def __init__(self, sleep_time: float):
        self.counter = count()
        self.sleep_time = sleep_time
        self.last = None

    def sleep(self):
        start = monotonic()
        self.last = next(self.counter)
        sleep(self.sleep_time)
        end = monotonic()
        return start, end

    @property
    @abstractmethod
    def bar(self) -> tuple[float, float]:
        raise NotImplementedError

    def get_bar(self) -> tuple[float, float]:
        return self.bar


def init_and_get_call_times(cls, num_calls: int = 3) -> list[tuple[float, float]]:
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = [executor.submit(cls(SLEEP_TIME).get_bar) for _ in range(num_calls)]
        times = [future.result() for future in as_completed(futures)]

    return times


def get_call_times(func, num_calls: int = 3) -> list[tuple[float, float]]:
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = [executor.submit(func) for _ in range(num_calls)]
        times = []
        for future in as_completed(futures):
            try:
                times.append(future.result())
            except TestError:
                pass

    return times


class CachedPropertyTest(TestCase):
    def test_get_cached_property_names(self):
        class D1(ClearableCachedProperty):
            def __get__(self, instance, owner):
                return self

        class D2(D1): pass  # noqa
        class D3: pass  # noqa
        class D4: pass  # noqa
        ClearableCachedProperty.register(D3)  # noqa
        class Foo:  # noqa
            a = D1()
            b = D2()
            c = D3()
            d = D4()

            @_functools.cached_property
            def e(self):
                return 1

            @cached_property
            def f(self):
                return 1

        self.assertSetEqual({'a', 'b', 'c', 'e', 'f'}, get_cached_property_names(Foo))
        with patch('ds_tools.caching.decorators.is_cached_property') as is_cached_property_mock:
            self.assertSetEqual({'a', 'b', 'c', 'e', 'f'}, get_cached_property_names(Foo()))
            is_cached_property_mock.assert_not_called()  # The result should be cached from the previous call above

    def test_get_with_no_instance(self):
        class Foo:
            @cached_property
            def bar(self):
                return 5

        self.assertIsInstance(Foo.bar, CachedProperty)

    def test_reassign_name_error(self):
        with self.assertRaisesRegex(RuntimeError, 'Error calling __set_name__ on') as exc_ctx:
            class Foo:
                @cached_property
                def bar(self):
                    return 1
                baz = bar  # this triggers the expected exception

        original_exc = exc_ctx.exception.__cause__
        self.assertRegex(str(original_exc), 'Cannot assign the same')

    def test_reassign_same_name_ok(self):
        class Foo:
            @cached_property
            def bar(self):
                return 1

        self.assertIs(None, Foo.bar.__set_name__(Foo, 'bar'))  # noqa

    def test_unnamed_error(self):
        class Foo:
            @cached_property(block=False)
            def bar(self):
                return 1

        Foo.bar.name = None
        with self.assertRaisesRegex(TypeError, 'Cannot use .* without calling __set_name__ on it'):
            _ = Foo().bar

    def test_no_dict_error(self):
        class Foo:
            __slots__ = ()

            @cached_property(block=False)
            def bar(self):
                return 1

        with self.assertRaisesRegex(TypeError, r'Unable to cache Foo\.bar because Foo has no .__dict__. attribute'):
            _ = Foo().bar

    def test_immutable_dict_error(self):
        class ImmutableDict(dict):
            def __setitem__(self, key, value):
                raise TypeError

        class Foo:
            __slots__ = ('__dict__',)

            def __init__(self):
                self.__dict__ = ImmutableDict()

            @cached_property(block=False)
            def bar(self):
                return 1

        with self.assertRaisesRegex(TypeError, r'Unable to cache Foo\.bar because Foo\.__dict__ does not support'):
            _ = Foo().bar

    def test_init_fully_via_wrapper(self):
        prop = cached_property(lambda: 5, block=False)
        self.assertIsInstance(prop, CachedProperty)
        self.assertFalse(prop.block)

    # region Cross Instance Blocking Tests

    def test_other_instances_do_not_block_instance_blocking(self):
        class Foo(ConcurrentAccessBase):
            @cached_property
            def bar(self):
                return self.sleep()

        times = init_and_get_call_times(Foo)
        for start, _ in times:
            for _, end in times:
                self.assertLess(start, end)

    def test_other_instances_do_not_block_no_blocking(self):
        class Foo(ConcurrentAccessBase):
            @cached_property(block=False)
            def bar(self):
                return self.sleep()

        times = init_and_get_call_times(Foo)
        for start, _ in times:
            for _, end in times:
                self.assertLess(start, end)

    def test_other_instances_do_block(self):
        class Foo(ConcurrentAccessBase):
            @cached_property(block_all=True)
            def bar(self):
                return self.sleep()

        times = init_and_get_call_times(Foo)
        for i, (start, _) in enumerate(times):
            for _, end in times[i + 1:]:
                self.assertGreater(end, start)

    # endregion

    # region Same Instance Blocking Tests

    def test_other_threads_wait_instance_blocking(self):
        class Foo(ConcurrentAccessBase):
            @cached_property
            def bar(self):
                return self.sleep()

        times = get_call_times(Foo(SLEEP_TIME).get_bar)
        self.assertEqual(3, len(times))
        self.assertEqual(1, len(set(times)))

    def test_other_threads_wait_all_blocking(self):
        class Foo(ConcurrentAccessBase):
            @cached_property(block_all=True)
            def bar(self):
                return self.sleep()

        times = get_call_times(Foo(SLEEP_TIME).get_bar)
        self.assertEqual(3, len(times))
        self.assertEqual(1, len(set(times)))

    def test_other_threads_do_not_wait_no_blocking(self):
        class Foo(ConcurrentAccessBase):
            @cached_property(block=False)
            def bar(self):
                return self.sleep()

        foo = Foo(SLEEP_TIME)
        times = get_call_times(foo.get_bar)
        self.assertEqual(3, len(times))
        self.assertEqual(2, foo.last)

    # endregion

    def test_clear_properties(self):
        class Foo(ClearableCachedPropertyMixin, ConcurrentAccessBase):
            @cached_property(block=False)
            def bar(self):
                return next(self.counter)

            def baz(self):
                return 1

        foo = Foo(0.001)
        self.assertEqual(0, foo.bar)
        self.assertEqual(0, foo.bar)
        foo.clear_cached_properties()
        foo.clear_cached_properties()  # again for unittest to see key error. . .
        self.assertEqual(1, foo.bar)

    def test_clear_specific_properties(self):
        class Foo(ClearableCachedPropertyMixin, ConcurrentAccessBase):
            def __init__(self, sleep_time):
                super().__init__(sleep_time)
                self.counter_2 = count()

            @cached_property(block=False)
            def bar(self):
                return next(self.counter)

            @cached_property(block=False)
            def baz(self):
                return next(self.counter_2)

        foo = Foo(0.001)
        self.assertEqual(0, foo.bar)
        self.assertEqual(0, foo.baz)
        foo.clear_cached_properties('baz')
        self.assertEqual(0, foo.bar)
        self.assertEqual(1, foo.baz)
        foo.clear_cached_properties(skip='baz')
        self.assertEqual(1, foo.bar)
        self.assertEqual(1, foo.baz)
        foo.clear_cached_properties(skip=['baz'])
        self.assertEqual(2, foo.bar)
        self.assertEqual(1, foo.baz)

    def test_error_on_first_call(self):
        class Foo(ConcurrentAccessBase):
            @cached_property
            def bar(self):
                if not next(self.counter):
                    raise TestError
                return self.sleep()

        foo = Foo(SLEEP_TIME)
        times = get_call_times(foo.get_bar)
        self.assertEqual(2, len(times))
        self.assertEqual(1, len(set(times)))
        self.assertEqual(2, foo.last)


if __name__ == '__main__':
    try:
        main(verbosity=2, exit=False)
    except KeyboardInterrupt:
        print()
