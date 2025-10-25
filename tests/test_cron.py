#!/usr/bin/env python

from datetime import datetime
from unittest import TestCase, main
from unittest.mock import Mock

from ds_tools.utils.cron import CronSchedule, ExtCronSchedule, InvalidCronSchedule, InvalidCronPart
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

        with self.assertRaisesRegex(InvalidCronPart, 'Invalid hour='):
            ExtCronSchedule('0 0 3-1,5,7-12,20 * * *')

        # with self.assertRaises(ValueError):
        #     cron = ExtCronSchedule('0 0 3-3,5,7-12,20 * * *')

    def test_daily_dows(self):
        self.assertEqual('0 15 6 * * 0,5-6', str(ExtCronSchedule('0 15 6 * * 0,5,6')))

    def test_irregular_dow_with_week(self):
        self.assertEqual('0 23 * * 1#3,2#1,3#L', str(CronSchedule('0 23 * * 2#1,1#3,3#L')))

    def test_parts_all(self):
        cron = CronSchedule('15 9-17 */3 * *')
        self.assertFalse(cron.minute.all())
        self.assertFalse(cron.hour.all())
        self.assertFalse(cron.day.all())
        self.assertTrue(cron.month.all())
        self.assertTrue(cron.dow.all())

    def test_dow_not_all(self):
        self.assertFalse(CronSchedule('0 23 * * 2#1,1#3,3#L').dow.all())

    def test_month_iter(self):
        self.assertEqual(list(range(1, 13)), list(CronSchedule('* * * * *').month))
        self.assertEqual(list(range(12, 0, -1)), list(reversed(CronSchedule('* * * * *').month)))

    def test_dt_matches(self):
        true_cases = [
            ('* * * * *', datetime.now()),
            ('*/5 10 1-9 * *', datetime(2025, 10, 4, 10, 30, 28)),
        ]
        false_cases = [
            ('*/5 10 1-9 * *', datetime(2025, 10, 4, 10, 31, 28)),
        ]
        for cron_str, dt in true_cases:
            with self.subTest(cron_str=cron_str, dt=dt):
                self.assertTrue(CronSchedule(cron_str).matches(dt))

        for cron_str, dt in false_cases:
            with self.subTest(cron_str=cron_str, dt=dt):
                self.assertFalse(CronSchedule(cron_str).matches(dt))

    def test_match_generation(self):
        cron = CronSchedule('*/27 2 4 7,9 *')
        self.assertEqual(datetime(2025, 7, 4, 2, 0, 0), cron.first_match_of_year(2025))
        expected = [
            datetime(2025, 7, 4, 2, 0, 0), datetime(2025, 7, 4, 2, 27, 0), datetime(2025, 7, 4, 2, 54, 0),
            datetime(2025, 9, 4, 2, 0, 0), datetime(2025, 9, 4, 2, 27, 0), datetime(2025, 9, 4, 2, 54, 0),
        ]
        self.assertEqual(expected, list(cron.matching_datetimes(2025)))

    def test_reverse_generation(self):
        cron = CronSchedule('*/27 2 4 7,9 *')
        self.assertEqual(datetime(2025, 9, 4, 2, 54, 0), cron.last_match_of_year(2025))
        expected = [
            datetime(2025, 9, 4, 2, 54, 0), datetime(2025, 9, 4, 2, 27, 0), datetime(2025, 9, 4, 2, 0, 0),
            datetime(2025, 7, 4, 2, 54, 0), datetime(2025, 7, 4, 2, 27, 0), datetime(2025, 7, 4, 2, 0, 0),
        ]
        self.assertEqual(expected, list(cron.matching_datetimes(2025, reverse=True)))


class WinCronTest(TestCase):
    def test_min_max_values(self):
        cron = WinCronSchedule('* * * * * *')
        for val in (0, 32, -1):
            with self.subTest(f'day[{val}]'):
                with self.assertRaises(IndexError):
                    cron.day[val] = True

        cron.day[1] = True
        cron.day[31] = True
        self.assertTrue(cron.day[31])

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
