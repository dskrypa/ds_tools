#!/usr/bin/env python

import logging
import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

sys.path.append(Path(__file__).parents[1].as_posix())
from ds_tools.logging import init_logging
from ds_tools.test_common import TestCaseBase, main
from ds_tools.utils.cron import CronSchedule
from ds_tools.windows.scheduler.win_cron import WinCronSchedule

log = logging.getLogger(__name__)


class WinCronTest(TestCaseBase):
    def test_from_cron_str(self):
        cron = CronSchedule.from_cron('0 0 23 * * *')
        for attr in (cron._second, cron._minute):
            self.assertTrue(attr[0])
            for i in range(1, 60):
                self.assertFalse(attr[i])

        self.assertTrue(cron._hour[23])
        for i in range(23):
            self.assertFalse(cron._hour[i])

        for attr in (cron._day, cron._month, cron._dow):
            self.assertTrue(all(attr.values()))

    def test_in_equals_out(self):
        cron_str = '0 0 23 * * *'
        cron = CronSchedule.from_cron(cron_str)
        self.assertEqual(cron_str, str(cron))

    def test_start(self):
        cron = CronSchedule.from_cron('0 0 23 * * *')
        expected = datetime.now().replace(second=0, minute=0, hour=23, microsecond=0)
        self.assertEqual(expected, cron.start)

    def test_win_interval(self):
        cron = WinCronSchedule.from_cron('0 0 23 * * *')
        self.assertEqual(cron.interval, 'P1D')

    def test_monthly_dow_last(self):
        cron = WinCronSchedule.from_trigger(mock_monthly_dow_trigger(3, 4095, 3, True))
        self.assertEqual('0 0 0 * * 0#1,0#2,0#L,1#1,1#2,1#L', str(cron))

    def test_monthly_dow(self):
        cron = WinCronSchedule.from_trigger(mock_monthly_dow_trigger(3, 4095, 15))
        self.assertEqual('0 0 0 * * 0-1', str(cron))

    def test_monthly_dow_all(self):
        cron = WinCronSchedule.from_trigger(mock_monthly_dow_trigger(2147483647, 4095, 15))
        self.assertEqual('0 0 0 * * *', str(cron))

    def test_monthly_dow_feb_thru_dec(self):
        cron = WinCronSchedule.from_trigger(mock_monthly_dow_trigger(2147483647, 4094, 15))
        self.assertEqual('0 0 0 * 2-12 *', str(cron))

    def test_monthly_dow_jan(self):
        cron = WinCronSchedule.from_trigger(mock_monthly_dow_trigger(2147483647, 1, 15))
        self.assertEqual('0 0 0 * 1 *', str(cron))

    def test_first_last_dom(self):
        cron = CronSchedule.from_cron('0 0 23 1,L * *')
        self.assertEqual('0 0 23 1,L * *', str(cron))

    def test_last_dom(self):
        cron = CronSchedule.from_cron('0 0 23 L * *')
        self.assertEqual('0 0 23 L * *', str(cron))

    def test_ranges(self):
        cron = CronSchedule.from_cron('0 0 1-3,5,7-12 * * *')
        self.assertEqual('0 0 1-3,5,7-12 * * *', str(cron))

        cron = CronSchedule.from_cron('0 0 1-3,5,7-12,20 * * *')
        self.assertEqual('0 0 1-3,5,7-12,20 * * *', str(cron))

        with self.assertRaises(ValueError):
            cron = CronSchedule.from_cron('0 0 3-1,5,7-12,20 * * *')

        with self.assertRaises(ValueError):
            cron = CronSchedule.from_cron('0 0 3-3,5,7-12,20 * * *')

    def test_daily_dows(self):
        cron = CronSchedule.from_cron('0 15 6 * * 0,5,6')
        self.assertEqual('0 15 6 * * 0,5-6', str(cron))


def mock_monthly_dow_trigger(dow, moy, wom, lwom=False):
    start = datetime.now().replace(second=0, minute=0, hour=0, microsecond=0).isoformat()
    mock = MagicMock(
        Type=5, StartBoundary=start, DaysOfWeek=dow, MonthsOfYear=moy, WeeksOfMonth=wom, RunOnLastWeekOfMonth=lwom
    )
    return mock


if __name__ == '__main__':
    main()
