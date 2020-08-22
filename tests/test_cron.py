#!/usr/bin/env python

import logging
import sys
from datetime import datetime
from pathlib import Path

sys.path.append(Path(__file__).parents[1].as_posix())
from ds_tools.logging import init_logging
from ds_tools.test_common import TestCaseBase, main
from ds_tools.windows.scheduler.win_cron import WinCronSchedule

log = logging.getLogger(__name__)


class WinCronTest(TestCaseBase):
    def test_from_cron_str(self):
        cron = WinCronSchedule.from_cron('0 0 23 * * *')
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
        cron = WinCronSchedule.from_cron(cron_str)
        self.assertEqual(cron_str, str(cron))

    def test_start(self):
        cron = WinCronSchedule.from_cron('0 0 23 * * *')
        expected = datetime.now().replace(second=0, minute=0, hour=23, microsecond=0)
        self.assertEqual(expected, cron.start)

    def test_win_interval(self):
        cron = WinCronSchedule.from_cron('0 0 23 * * *')
        self.assertEqual(cron.interval, 'P1D')


if __name__ == '__main__':
    main()
