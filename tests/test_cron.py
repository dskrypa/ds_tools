#!/usr/bin/env python

from datetime import datetime
from unittest import TestCase, main
from unittest.mock import Mock

from ds_tools.utils.cron import CronSchedule, ExtCronSchedule, InvalidCronSchedule
from ds_tools.windows.scheduler.win_cron import WinCronSchedule


class CronTest(TestCase):
    def test_too_few_parts(self):
        with self.assertRaises(InvalidCronSchedule):
            CronSchedule('* * * *')

    def test_too_many_parts(self):
        with self.assertRaises(InvalidCronSchedule):
            CronSchedule('* * * * * *')

    def test_from_cron_str(self):
        cron = ExtCronSchedule('0 0 23 * * *')
        for attr in (cron.second, cron.minute):
            self.assertTrue(attr[0])
            for i in range(1, 60):
                self.assertFalse(attr[i])

        self.assertTrue(cron.hour[23])
        for i in range(23):
            self.assertFalse(cron.hour[i])

        for attr in (cron.day, cron.month, cron.dow):
            self.assertTrue(attr.arr.all())

    def test_in_equals_out(self):
        cron_str = '0 23 * * *'
        self.assertEqual(cron_str, str(CronSchedule(cron_str)))

    def test_in_equals_out_ext(self):
        cron_str = '0 0 23 * * *'
        self.assertEqual(cron_str, str(ExtCronSchedule(cron_str)))

    def test_first_last_dom(self):
        self.assertEqual('0 0 23 1,L * *', str(ExtCronSchedule('0 0 23 1,L * *')))

    def test_last_dom(self):
        self.assertEqual('0 0 23 L * *', str(ExtCronSchedule('0 0 23 L * *')))

    def test_ranges(self):
        cron = ExtCronSchedule('0 0 1-3,5,7-12 * * *')
        self.assertEqual('0 0 1-3,5,7-12 * * *', str(cron))

        cron = ExtCronSchedule('0 0 1-3,5,7-12,20 * * *')
        self.assertEqual('0 0 1-3,5,7-12,20 * * *', str(cron))

        with self.assertRaises(InvalidCronSchedule):
            ExtCronSchedule('0 0 3-1,5,7-12,20 * * *')

        # with self.assertRaises(ValueError):
        #     cron = ExtCronSchedule('0 0 3-3,5,7-12,20 * * *')

    def test_daily_dows(self):
        self.assertEqual('0 15 6 * * 0,5-6', str(ExtCronSchedule('0 15 6 * * 0,5,6')))

    def test_min_max_values(self):
        cron = ExtCronSchedule('* * * * * *')
        attrs = ('day', 'day', 'day', '_week', '_week', '_week')
        for attr, val in zip(attrs, (0, 32, -1, 0, 7, -1)):
            with self.subTest(f'{attr}[{val}]'):
                with self.assertRaises(IndexError):
                    getattr(cron, attr)[val] = True

        cron.day[1] = True
        cron.day[31] = True
        cron._week[1] = True
        cron._week[5] = True
        self.assertTrue(cron.day[31])


class WinCronTest(TestCase):
    def test_start(self):
        cron = WinCronSchedule('0 0 23 * * *')
        expected = datetime.now().replace(second=0, minute=0, hour=23, microsecond=0)
        self.assertEqual(expected, cron.start)

    def test_win_interval(self):
        self.assertEqual(WinCronSchedule('0 0 23 * * *').interval, 'P1D')

    def test_monthly_dow_last(self):
        cron = WinCronSchedule.from_trigger(mock_monthly_dow_trigger(3, 4095, 3, True))
        self.assertEqual('0 0 0 * * 0#1,0#2,0#L,1#1,1#2,1#L', str(cron))

    def test_monthly_dow(self):
        cron = WinCronSchedule.from_trigger(mock_monthly_dow_trigger(3, 4095, pack_all(6)))
        self.assertEqual('0 0 0 * * 0-1', str(cron))

    def test_monthly_dow_all(self):
        cron = WinCronSchedule.from_trigger(mock_monthly_dow_trigger(2147483647, 4095, pack_all(6)))
        self.assertEqual('0 0 0 * * *', str(cron))

    def test_monthly_dow_feb_thru_dec(self):
        cron = WinCronSchedule.from_trigger(mock_monthly_dow_trigger(2147483647, 4094, 15))
        self.assertEqual('0 0 0 * 2-12 *', str(cron))

    def test_monthly_dow_jan(self):
        cron = WinCronSchedule.from_trigger(mock_monthly_dow_trigger(2147483647, 1, 15))
        self.assertEqual('0 0 0 * 1 *', str(cron))


def pack_all(count):
    return (1 << count) - 1


def mock_monthly_dow_trigger(dow, moy, wom, lwom=False):
    start = datetime.now().replace(second=0, minute=0, hour=0, microsecond=0).isoformat()
    return Mock(
        Type=5, StartBoundary=start, DaysOfWeek=dow, MonthsOfYear=moy, WeeksOfMonth=wom, RunOnLastWeekOfMonth=lwom
    )


if __name__ == '__main__':
    main(verbosity=2)
