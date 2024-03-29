"""
:author: Doug Skrypa
"""

from itertools import cycle
from time import monotonic

from ..core.decorate import basic_coroutine
from ..output.formatting import readable_bytes, format_duration

__all__ = ['progress_coroutine']


@basic_coroutine
def progress_coroutine(total: float, name: str, unit: str = 'parts', interval: float = 0.3):
    """Display progress"""
    fmt = f'\r{{:8}} {{:,.03f}} {unit}/s {{:>9}}/s {{:6.2%}} [{{:10}}] [{total}] {name}'
    spinner = cycle('|/-\\')
    last_time, elapsed, item_rate, byte_rate, pct, total_bytes = 0, 0, 0, 0, 0, 0
    end = ''
    started = monotonic()

    while pct < 1:
        parts, bytes_read = yield
        total_bytes += bytes_read
        pct = parts / total
        elapsed = monotonic() - started
        item_rate = (parts / elapsed) if elapsed else 0
        byte_rate = readable_bytes((total_bytes / elapsed) if elapsed else 0)

        if monotonic() - last_time > interval or pct == 1:
            pct_chars = int(pct * 10)
            if pct_chars == 10:
                end = '\n'
                bar = '=' * 10
            else:
                bar = '{}{}{}'.format('=' * pct_chars, next(spinner), ' ' * (9 - pct_chars))
            print(fmt.format(format_duration(int(elapsed)), item_rate, byte_rate, pct, bar), end=end)
            last_time = monotonic()
