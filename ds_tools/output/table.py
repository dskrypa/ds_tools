"""
Table and supporting classes for formatting / printing tabular data to stdout.

:author: Doug Skrypa
"""

import csv
import logging
import re
from io import StringIO
from unicodedata import normalize

from wcwidth import wcswidth

from ..core import cached_property
from .color import colored
from .exceptions import TableFormatException
from .terminal import uprint, _uout, Terminal

__all__ = ['Column', 'SimpleColumn', 'Table', 'TableBar']
log = logging.getLogger(__name__)

ANSI_COLOR_RX = re.compile('(\033\[\d+;?\d*;?\d*m)(.*)(\033\[\d+;?\d*;?\d*m)')
TERM = Terminal()


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
    def row_fmt(self):
        return '{{0[{}]:{}{}{}}}'.format(self.key, self.align, self.width, self.ftype)

    @property
    def header_fmt(self):
        return '{{0[{}]:{}{}}}'.format(self.key, self.align, self.width)

    def format(self, value):
        orig_width = self._width
        test_val = self._test_fmt.format(value)
        char_count = len(test_val)
        str_width = mono_width(test_val)
        if char_count != str_width and str_width > 0:
            diff = str_width - char_count
            self._width -= diff

        try:
            if self.formatter:
                try:
                    col = self.row_fmt.format({self.key: value})
                except ValueError:
                    col = self.header_fmt.format({self.key: value})
                return self.formatter(value, col)
            else:
                prefix, suffix = '', ''
                if isinstance(value, str):
                    m = ANSI_COLOR_RX.match(value)
                    if m:
                        prefix, value, suffix = m.groups()
                try:
                    return prefix + self.row_fmt.format({self.key: value}) + suffix
                except ValueError:
                    return prefix + self.header_fmt.format({self.key: value}) + suffix
        except TypeError as e:
            raise TableFormatException('column', self.row_fmt, value, e) from e
        finally:
            self._width = orig_width

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
                    return max(self._len(fmt.format(obj)) for obj in width)


class SimpleColumn(Column):
    """
    An output column metadata handler

    :param str title: Column header & row key associated with this column
    :param width: Width of this column (can auto-detect if passed values for this column)
    :param bool display: Include this column in output (default: True)
    :param str align: String formatting alignment indicator (default: left; example: '>' for right)
    :param str ftype: String formatting type/format indicator (default: none; example: ',d' for thousands indicator)
    """

    def __init__(self, title, width=0, display=True, align='', ftype='', formatter=None):
        super().__init__(title, title, width, display, align, ftype, formatter)


class TableBar:
    def __getitem__(self, item):
        return None


class Table:
    def __init__(self, *columns, mode='table', auto_header=True, auto_bar=True, sort=False, sort_by=None,
                 update_width=False, fix_ansi_width=False):
        if mode not in ('table', 'csv'):
            raise ValueError('Invalid output mode: {}'.format(mode))
        self.mode = mode
        self.columns = [c for c in columns if c.display]
        self.auto_header = auto_header
        self.auto_bar = auto_bar
        self.sort = sort
        self.sort_by = sort_by
        self.update_width = update_width
        self.fix_ansi_width = fix_ansi_width

    def __getitem__(self, item):
        for c in self.columns:
            if c.key == item:
                return c
        raise KeyError(item)

    @cached_property
    def keys(self):
        return [c.key for c in self.columns]

    @cached_property
    def csv_writer(self):
        return csv.DictWriter(_uout, self.keys)

    @cached_property
    def header_fmt(self):
        return '  '.join(c.header_fmt for c in self.columns)

    @cached_property
    def headers(self):
        return {c.key: c.title for c in self.columns if c.display}

    @cached_property
    def row_fmt(self):
        return '  '.join(c.row_fmt for c in self.columns)

    @cached_property
    def has_custom_formatter(self):
        return any(c.formatter is not None for c in self.columns)

    @cached_property
    def header_row(self):
        if self.mode == 'csv':
            return self.format_row(self.headers)
        elif self.mode == 'table':
            return self.header_fmt.format(self.headers)

    @cached_property
    def header_bar(self):
        if self.mode == 'table':
            return '-' * len(self.header_row)
        return None

    @classmethod
    def auto_print_rows(cls, rows, header=True, bar=True, sort=False, sort_by=None, mode='table'):
        if len(rows) < 1:
            return
        if isinstance(rows, dict):
            rows = [row for row in rows.values()]

        keys = sorted(rows[0].keys()) if type(rows[0]) is dict else rows[0].keys()
        tbl = Table(*[Column(k, k, rows) for k in keys], mode=mode, auto_header=header, auto_bar=bar, sort=sort,
                    sort_by=sort_by)
        tbl.print_rows(rows)

    @classmethod
    def auto_format_rows(cls, rows, header=True, bar=True, sort=False, sort_by=None, mode='table'):
        if len(rows) < 1:
            return
        if isinstance(rows, dict):
            rows = [row for row in rows.values()]

        keys = sorted(rows[0].keys()) if type(rows[0]) is dict else rows[0].keys()
        tbl = Table(*[Column(k, k, rows) for k in keys], mode=mode, sort=sort, sort_by=sort_by)
        output_rows = tbl.format_rows(rows)
        if header:
            if bar and mode == 'table':
                output_rows.insert(0, tbl.header_bar)
            output_rows.insert(0, tbl.header_row)
        return output_rows

    def print_header(self, add_bar=True):
        self.auto_header = False
        if self.mode == 'csv':
            self.print_row(self.headers)
        elif self.mode == 'table':
            uprint(self.header_row.rstrip())
            if add_bar or self.auto_bar:
                self.print_bar()

    def print_bar(self):
        self.auto_bar = False
        if self.mode == 'table':
            uprint(self.header_bar[:TERM.width])

    def _csv_str(self, content):
        si = StringIO()
        writer = csv.DictWriter(si, self.keys)
        if isinstance(content, dict):
            writer.writerow({k: content[k] for k in self.keys})
        elif isinstance(content, list):
            writer.writerows(content)
        return si.getvalue()

    def format_row(self, row_dict):
        """
        Format the given row using the `row_fmt` that was generated based on the columns defined for this table.

        The following error meands that one of the values needs to be converted to an appropriate type, or the format
        specification needs to be fixed (e.g., formatting a list as the value when a column width was specified):
        ::
            TypeError: non-empty format string passed to object.__format__

        :param dict row_dict: Mapping of {column key: row value} pairs
        :return str: The formatted row
        :raises TypeError: if one of the values has a type that is incompatible with the format string
        """
        if self.mode == 'csv':
            return self._csv_str(row_dict)
        elif self.mode == 'table':
            # Don't str() the row_dict[k] value! That will break type-specific format strings (e.g., int/float)
            row = {k: row_dict[k] if row_dict[k] is not None else '' for k in self.keys}

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
                    row_str = self.header_fmt.format(row)
                    if self.fix_ansi_width and ANSI_COLOR_RX.search(row_str):
                        row_str = '  '.join(c.format(row[c.key]) for c in self.columns)
            return row_str.rstrip()

    def print_row(self, row_dict, color=None):
        if self.auto_header:
            self.print_header()
        if self.mode == 'csv':
            self.csv_writer.writerow({k: row_dict[k] for k in self.keys})
        elif self.mode == 'table':
            if color is not None:
                uprint(colored(self.format_row(row_dict), color))
            else:
                uprint(self.format_row(row_dict))

    def sorted(self, rows):
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

    def format_rows(self, rows):
        rows = self.sorted(rows)
        if self.mode == 'csv':
            return list(self._csv_str(rows).splitlines())
        elif self.mode == 'table':
            return [self.format_row(row) for row in rows]

    def print_rows(self, rows):
        rows = self.sorted(rows)
        if self.update_width:
            for col in self.columns:
                col.width = [row[col.key] for row in rows]

        if self.auto_header:
            self.print_header()
        try:
            if self.mode == 'csv':
                self.csv_writer.writerows(rows)
            elif self.mode == 'table':
                for row in rows:
                    if isinstance(row, TableBar) or row is TableBar:
                        self.print_bar()
                    else:
                        uprint(self.format_row(row))
        except IOError as e:
            if e.errno == 32:  #broken pipe
                return


def mono_width(text):
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
