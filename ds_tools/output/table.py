"""
Table and supporting classes for formatting / printing tabular data to stdout.

:author: Doug Skrypa
"""

import csv
import re
import sys
from contextlib import contextmanager
from functools import cached_property
from io import StringIO
from shutil import get_terminal_size
from types import GeneratorType
from typing import Union, Collection, TextIO, Optional, List, Dict, Mapping, Any, Type, Iterable
from unicodedata import normalize

from wcwidth import wcswidth

from ..caching.mixins import ClearableCachedPropertyMixin
from .color import colored

__all__ = ['Column', 'SimpleColumn', 'Table', 'TableBar', 'HeaderRow', 'TableFormatException']

ANSI_COLOR_RX = re.compile(r'(\033\[\d+;?\d*;?\d*m)(.*)(\033\[\d+;?\d*;?\d*m)')
Row = Union[Mapping[str, Any], 'TableBar', 'HeaderRow', Type['TableBar'], Type['HeaderRow']]


class Column:
    """
    An output column metadata handler

    Column width can be specified literally or determined dynamically...
    - If width is a number, then that value is used
    - If width is a collection, then the maximum length of the relevant elements that it contains is used
    - Relevant element discovery logic:
        - Treat width as a dict with .values() being dicts that contain an element with the given key
        - Treat width as a sequence with values being dicts that contain an element with the given key
        - Treat width as a sequence where all values are relevant
    - If the length of the title is greater than the current width, take that length instead

    :param str key: Row key associated with this column
    :param str title: Column header
    :param width: Width of this column (can auto-detect if passed values for this column)
    :param bool display: Include this column in output (default: True)
    :param str align: String formatting alignment indicator (default: left; example: '>' for right)
    :param str ftype: String formatting type/format indicator (default: none; example: ',d' for thousands indicator)
    """

    __slots__ = ('key', 'title', '_width', 'display', 'align', 'ftype', 'formatter')

    def __init__(self, key, title, width, display=True, align='', ftype='', formatter=None):
        self.key = key
        self.title = str(title)
        self._width = 0
        self.display = display
        self.align = align
        self.ftype = ftype
        self.formatter = formatter
        self.width = width

    def __repr__(self):
        return '<{}({!r}, {!r})>'.format(type(self).__name__, self.key, self.title)

    @property
    def _test_fmt(self):
        return '{{:{}{}}}'.format(self.align, self.ftype)

    @property
    def _row_fmt(self):
        return '{{:{}{}{}}}'.format(self.align, self.width, self.ftype)

    @property
    def row_fmt(self):
        return '{{0[{}]:{}{}{}}}'.format(self.key, self.align, self.width, self.ftype)

    @property
    def _header_fmt(self):
        return '{{:{}{}}}'.format(self.align, self.width)

    @property
    def header_fmt(self):
        return '{{0[{}]:{}{}}}'.format(self.key, self.align, self.width)

    @contextmanager
    def _temp_width(self, value):
        orig_width = self._width
        try:
            test_val = self._test_fmt.format(value)
        except ValueError:
            test_val = str(value)

        char_count = len(test_val)
        str_width = mono_width(test_val)
        if char_count != str_width and str_width > 0:
            diff = str_width - char_count
            self._width -= diff

        try:
            yield
        finally:
            self._width = orig_width

    def _format(self, value):
        try:
            return self._row_fmt.format(value)
        except ValueError:
            return self._header_fmt.format(value)

    def format(self, value):
        with self._temp_width(value):
            try:
                if self.formatter:
                    return self.formatter(value, self._format(value))
                else:
                    if isinstance(value, str) and (m := ANSI_COLOR_RX.match(value)):
                        prefix, value, suffix = m.groups()
                        return prefix + self._format(value) + suffix
                    else:
                        return self._format(value)
            except TypeError as e:
                raise TableFormatException('column', self.row_fmt, value, e) from e

    @property
    def width(self):
        return self._width

    @width.setter
    def width(self, value):
        try:
            self._width = max(self._calc_width(value), mono_width(self.title))
        except (ValueError, TypeError) as e:
            try:
                raise ValueError('{}: Unable to determine width (likely no values were found)'.format(self)) from e
            except ValueError as e2:
                raise ValueError('No results.') from e2

    def _len(self, text):
        char_count = len(text)
        str_width = mono_width(text)
        if (char_count != str_width) and not self.formatter:
            self.formatter = lambda a, b: b  # Force Table.format_row to delegate formatting to Column.format
        return str_width

    def _calc_width(self, width):
        fmt = self._test_fmt
        try:
            return int(width)
        except TypeError:
            try:
                return max(self._len(fmt.format(e[self.key])) for e in width.values())
            except (KeyError, TypeError, AttributeError):
                try:
                    return max(self._len(fmt.format(e[self.key])) for e in width)
                except (KeyError, TypeError, AttributeError):
                    try:
                        return max(self._len(fmt.format(obj)) for obj in width)
                    except ValueError as e:
                        if 'Unknown format code' in str(e):
                            values = []
                            for obj in width:
                                try:
                                    values.append(fmt.format(obj))
                                except ValueError:
                                    values.append(str(obj))
                            return max(self._len(val) for val in values)


class SimpleColumn(Column):
    """
    An output column metadata handler

    :param str title: Column header & row key associated with this column
    :param width: Width of this column (can auto-detect if passed values for this column)
    :param bool display: Include this column in output (default: True)
    :param str align: String formatting alignment indicator (default: left; example: '>' for right)
    :param str ftype: String formatting type/format indicator (default: none; example: ',d' for thousands indicator)
    """
    __slots__ = ()

    def __init__(self, title, width=0, display=True, align='', ftype='', formatter=None):
        super().__init__(title, title, width, display, align, ftype, formatter)


class TableBar:
    char = '-'

    def __init__(self, char: str = '-'):
        self.char = char

    def __getitem__(self, item):
        return None


class HeaderRow:
    bar = False

    def __init__(self, bar: bool = False):
        self.bar = bar

    def __getitem__(self, item):
        return None


class Table(ClearableCachedPropertyMixin):
    def __init__(
        self,
        *columns: Union[Column, SimpleColumn],
        mode: str = 'table',
        auto_header: bool = True,
        auto_bar: bool = True,
        sort: bool = False,
        sort_by: Union[Collection, str, None] = None,
        update_width: bool = False,
        fix_ansi_width: bool = False,
        file: Optional[TextIO] = None,
    ):
        if mode not in ('table', 'csv'):
            raise ValueError(f'Invalid output mode: {mode}')
        self.mode = mode
        self._columns = list(columns[0] if len(columns) == 1 and isinstance(columns[0], GeneratorType) else columns)
        self.auto_header = auto_header
        self.auto_bar = auto_bar
        self.sort = sort
        self.sort_by = sort_by
        self.update_width = update_width
        self.fix_ansi_width = fix_ansi_width
        self._flush = file is None
        if file is not None:
            self._file = file
            self._stdout = False
        else:
            self._stdout = True
            if sys.stdout.encoding.lower().startswith('utf'):
                self._file = sys.stdout
            else:
                self._file = open(sys.stdout.fileno(), mode='w', encoding='utf-8', buffering=1)

    def __getitem__(self, item):
        for c in self.columns:
            if c.key == item:
                return c
        raise KeyError(item)

    def append(self, column: Union[Column, SimpleColumn]):
        self._columns.append(column)
        if column.display:
            self.clear_cached_properties()

    def toggle_display(self, key: str, display: bool = None):
        column = self[key]
        column.display = (not column.display) if display is None else display
        self.clear_cached_properties()

    @cached_property
    def columns(self) -> List[Union[Column, SimpleColumn]]:
        return [c for c in self._columns if c.display]

    @cached_property
    def keys(self) -> List[str]:
        return [c.key for c in self.columns]

    @cached_property
    def csv_writer(self) -> csv.DictWriter:
        return csv.DictWriter(self._file, self.keys)

    @cached_property
    def header_fmt(self) -> str:
        return '  '.join(c.header_fmt for c in self.columns)

    @cached_property
    def headers(self) -> Dict[str, str]:
        return {c.key: c.title for c in self.columns if c.display}

    @cached_property
    def row_fmt(self) -> str:
        return '  '.join(c.row_fmt for c in self.columns)

    @cached_property
    def has_custom_formatter(self) -> bool:
        return any(c.formatter is not None for c in self.columns)

    @cached_property
    def header_row(self) -> str:
        if self.mode == 'csv':
            return self.format_row(self.headers)
        elif self.mode == 'table':
            return self.header_fmt.format(self.headers)
        else:
            raise ValueError(f'Invalid table mode={self.mode!r}')

    def header_bar(self, char: str = '-') -> Optional[str]:
        if self.mode == 'table':
            bar = char * len(self.header_row)
            return bar[:get_terminal_size().columns] if self._stdout else bar
        return None

    @classmethod
    def auto_print_rows(
        cls, rows, header=True, bar=True, sort=False, sort_by=None, mode='table', sort_keys=True, **kwargs
    ):
        if len(rows) < 1:
            return
        if isinstance(rows, dict):
            rows = [row for row in rows.values()]

        keys = sorted(rows[0].keys()) if type(rows[0]) is dict and sort_keys else rows[0].keys()
        tbl = Table(
            *[Column(k, k, rows) for k in keys],
            mode=mode,
            auto_header=header,
            auto_bar=bar,
            sort=sort,
            sort_by=sort_by,
            **kwargs
        )
        tbl.print_rows(rows)

    @classmethod
    def auto_format_rows(cls, rows, header=True, bar=True, sort=False, sort_by=None, mode='table', **kwargs):
        if len(rows) < 1:
            return
        if isinstance(rows, dict):
            rows = [row for row in rows.values()]

        keys = sorted(rows[0].keys()) if type(rows[0]) is dict else rows[0].keys()
        tbl = Table(*[Column(k, k, rows) for k in keys], mode=mode, sort=sort, sort_by=sort_by, **kwargs)
        output_rows = tbl.format_rows(rows)
        if header:
            if bar and mode == 'table':
                output_rows.insert(0, tbl.header_bar())
            output_rows.insert(0, tbl.header_row.rstrip())
        return output_rows

    def _print(self, content: str, color: Union[str, int, None] = None):
        if color is not None:
            content = colored(content, color)
        self._file.write(content + '\n')
        if self._flush:
            self._file.flush()

    def print_header(self, add_bar: bool = True, color: Union[str, int, None] = None):
        self.auto_header = False
        if self.mode == 'csv':
            self.print_row(self.headers, color)
        elif self.mode == 'table':
            self._print(self.header_row.rstrip(), color)
            if add_bar or self.auto_bar:
                self.print_bar(color=color)

    def print_bar(self, char: str = '-', color: Union[str, int, None] = None):
        self.auto_bar = False
        if self.mode == 'table':
            self._print(self.header_bar(char), color)

    def _csv_str(self, content):
        si = StringIO()
        writer = csv.DictWriter(si, self.keys)
        if isinstance(content, dict):
            writer.writerow({k: content[k] for k in self.keys})
        elif isinstance(content, list):
            writer.writerows(content)
        return si.getvalue()

    def format_row(self, row: Row) -> str:
        """
        Format the given row using the `row_fmt` that was generated based on the columns defined for this table.

        The following error means that one of the values needs to be converted to an appropriate type, or the format
        specification needs to be fixed (e.g., formatting a list as the value when a column width was specified):
        ::
            TypeError: non-empty format string passed to object.__format__

        :param row: Mapping of {column key: row value} pairs
        :return str: The formatted row
        :raises TypeError: if one of the values has a type that is incompatible with the format string
        """
        if self.mode == 'csv':
            return self._csv_str(row)
        elif self.mode == 'table':
            if isinstance(row, TableBar) or row is TableBar:
                return self.header_bar(row.char)
            elif isinstance(row, HeaderRow) or row is HeaderRow:
                return self.header_row

            # Don't str() the row[k] value! That will break type-specific format strings (e.g., int/float)
            row = {k: v if (v := row.get(k)) is not None else '' for k in self.keys}

            if self.has_custom_formatter:
                row_str = '  '.join(c.format(row[c.key]) for c in self.columns)
            else:
                try:
                    row_str = self.row_fmt.format(row)
                    if self.fix_ansi_width and ANSI_COLOR_RX.search(row_str):
                        row_str = '  '.join(c.format(row[c.key]) for c in self.columns)
                except TypeError as e:
                    raise TableFormatException('row', self.row_fmt, row, e) from e
                except ValueError:
                    row_str = '  '.join(c.format(row[c.key]) for c in self.columns)

            return row_str.rstrip()
        else:
            raise ValueError(f'Invalid table mode={self.mode!r}')

    def print_row(self, row: Row, color: Union[str, int, None] = None):
        if self.auto_header:
            self.print_header(color=color)
        if self.mode == 'csv':
            self.csv_writer.writerow({k: row[k] for k in self.keys})
        elif self.mode == 'table':
            # Use print_header for headers, but bars can be handled by format_row
            if isinstance(row, HeaderRow) or row is HeaderRow:
                self.print_header(row.bar, color)
            else:
                self._print(self.format_row(row), color)

    def sorted(self, rows: Iterable[Row]):
        if isinstance(rows, dict):
            rows = rows.values()

        if self.sort_by is not None:
            sort_by = [self.sort_by] if not isinstance(self.sort_by, (list, tuple, set)) else self.sort_by
            try:
                rows = sorted(rows, key=replacement_itemgetter(*sort_by, replacements={None: -1}))
            except TypeError:
                rows = sorted(rows, key=replacement_itemgetter(*sort_by, replacements={None: ''}))
        elif self.sort:
            rows = sorted(rows)

        if self.mode == 'csv':
            rows = [{k: row[k] for k in self.keys} for row in rows]
        return rows

    def format_rows(self, rows: Iterable[Row], full: bool = False) -> Union[List[str], str]:
        if self.mode == 'csv':
            rows = self.sorted(rows)
            return list(self._csv_str(rows).splitlines())
        elif self.mode == 'table':
            if full:
                orig_file, orig_flush = self._file, self._flush
                self._flush = False
                self._file = sio = StringIO()
                try:
                    self.print_rows(rows)
                    return sio.getvalue()
                finally:
                    self._file, self._flush = orig_file, orig_flush
            else:
                return [self.format_row(row) for row in self.sorted(rows)]

    def set_width(self, rows: Iterable[Row]):
        ignore = (TableBar, HeaderRow)
        for col in self.columns:
            values = (row.get(col.key) for row in rows if not isinstance(row, ignore) and row not in ignore)
            col.width = list(filter(None, values)) or 0

    def print_rows(
        self, rows: Iterable[Row], header: bool = False, update_width: bool = False, color: Union[str, int, None] = None
    ):
        rows = self.sorted(rows)
        if update_width or self.update_width:
            self.set_width(rows)

        if header or self.auto_header:
            self.print_header(color=color)
        try:
            if self.mode == 'csv':
                self.csv_writer.writerows(rows)
            elif self.mode == 'table':
                for row in rows:
                    # Use print_header for headers, but bars can be handled by format_row
                    if isinstance(row, HeaderRow) or row is HeaderRow:
                        self.print_header(row.bar, color)
                    else:
                        self._print(self.format_row(row), color)
        except IOError as e:
            if e.errno == 32:  # broken pipe
                return
            raise


def mono_width(text: str):
    return wcswidth(normalize('NFC', text))


class replacement_itemgetter:
    """
    Return a callable object that fetches the given item(s) from its operand.
    After f = itemgetter(2), the call f(r) returns r[2].
    After g = itemgetter(2, 5, 3), the call g(r) returns (r[2], r[5], r[3])
    """
    __slots__ = ('_items', '_call', '_repl')

    def __init__(self, item, *items, replacements=None):
        self._repl = replacements or {}
        if not items:
            self._items = (item,)
            def func(obj):
                val = obj[item]
                try:
                    return self._repl[val]
                except KeyError:
                    return val
            self._call = func
        else:
            self._items = items = (item,) + items
            def func(obj):
                vals = []
                for val in (obj[i] for i in items):
                    try:
                        vals.append(self._repl[val])
                    except KeyError:
                        vals.append(val)
                return tuple(vals)
            self._call = func

    def __call__(self, obj):
        return self._call(obj)


class TableFormatException(Exception):
    def __init__(self, scope, fmt_str, value, exc, *args):
        self.scope = scope
        self.fmt_str = fmt_str
        self.value = value
        self.exc = exc
        super().__init__(*args)

    def __str__(self):
        msg_fmt = 'Error formatting {}: {} {}\nFormat string: {!r}\nContent: {}'
        return msg_fmt.format(self.scope, type(self.exc).__name__, self.exc, self.fmt_str, self.value)
