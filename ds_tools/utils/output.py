#!/usr/bin/env python3

import csv
import json
import logging
import math
import pprint
import sys
import types
from io import StringIO
from collections import OrderedDict, namedtuple

import yaml
from termcolor import colored

from .decorate import cached_property
from .operator import replacement_itemgetter

__all__ = [
    "uprint", "uerror", "Column", "SimpleColumn", "Table", "readable_bytes", "format_output", "format_percent",
    "format_tiered", "print_tiered", "Printer", "to_bytes", "to_str"
]
log = logging.getLogger("ds_tools.utils.output")

_uout = open(sys.stdout.fileno(), mode="w", encoding="utf-8", buffering=1)
_uerr = open(sys.stderr.fileno(), mode="w", encoding="utf-8", buffering=1)

try:
    from blessings import Terminal
    term = Terminal(stream=_uout)
except ImportError:                                         # Fails in Windows
    term = namedtuple("Terminal", "width")(9999)


def to_bytes(data):
    if isinstance(data, str):
        return data.encode("utf-8")
    return data


def to_str(data):
    if isinstance(data, bytes):
        return data.decode("utf-8")
    return data


def uprint(msg):
    _uout.write(msg + "\n")
    _uout.flush()

def uerror(msg):
    _uerr.write(msg + "\n")
    _uerr.flush()


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
    :param str align: String formatting alignment indicator (default: left; example: ">" for right)
    :param str ftype: String formatting type/format indicator (default: none; example: ",d" for thousands indicator)
    """
    def __init__(self, key, title, width, display=True, align="", ftype=""):
        self.key = key
        self.title = str(title)
        self._width = 0
        self.width = width
        self.display = display
        self.align = align
        self.ftype = ftype

    def __repr__(self):
        return "<{}('{}', '{}')>".format(type(self).__name__, self.key, self.title)

    @property
    def row_fmt(self):
        return "{{0[{}]:{}{}{}}}".format(self.key, self.align, self.width, self.ftype)

    @property
    def header_fmt(self):
        return "{{0[{}]:{}{}}}".format(self.key, self.align, self.width)

    @property
    def width(self):
        return self._width

    @width.setter
    def width(self, value):
        try:
            self._width = max(self._calc_width(value), len(self.title))
        except (ValueError, TypeError) as e:
            try:
                raise ValueError("{}: Unable to determine width (likely no values were found)".format(self)) from e
            except ValueError as e2:
                raise ValueError("No results.") from e2

    def _calc_width(self, width):
        try:
            return int(width)
        except TypeError:
            try:
                return max(len(str(e[self.key])) for e in width.values())
            except (KeyError, TypeError, AttributeError):
                try:
                    return max(len(str(e[self.key])) for e in width)
                except (KeyError, TypeError, AttributeError):
                    return max(len(str(obj)) for obj in width)


class SimpleColumn(Column):
    """
    An output column metadata handler

    :param str title: Column header & row key associated with this column
    :param width: Width of this column (can auto-detect if passed values for this column)
    :param bool display: Include this column in output (default: True)
    :param str align: String formatting alignment indicator (default: left; example: ">" for right)
    :param str ftype: String formatting type/format indicator (default: none; example: ",d" for thousands indicator)
    """
    def __init__(self, title, width=0, display=True, align="", ftype=""):
        super().__init__(title, title, width, display, align, ftype)


class Table:
    def __init__(self, *columns, mode="table", auto_header=True, auto_bar=True, sort=False, sort_by=None, update_width=False):
        if mode not in ("table", "csv"):
            raise ValueError("Invalid output mode: {}".format(mode))
        self.mode = mode
        self.columns = [c for c in columns if c.display]
        self.auto_header = auto_header
        self.auto_bar = auto_bar
        self.sort = sort
        self.sort_by = sort_by
        self.update_width = update_width

    @cached_property
    def keys(self):
        return [c.key for c in self.columns]

    @cached_property
    def csv_writer(self):
        return csv.DictWriter(_uout, self.keys)
    
    @cached_property
    def header_fmt(self):
        return "  ".join(c.header_fmt for c in self.columns)
    
    @cached_property
    def headers(self):
        return {c.key: c.title for c in self.columns if c.display}
    
    @cached_property
    def row_fmt(self):
        return "  ".join(c.row_fmt for c in self.columns)
    
    @cached_property
    def header_row(self):
        if self.mode == "csv":
            return self.format_row(self.headers)
        elif self.mode == "table":
            return self.header_fmt.format(self.headers)
    
    @cached_property
    def header_bar(self):
        if self.mode == "table":
            return "-" * len(self.header_row)
        return None

    @classmethod
    def auto_print_rows(cls, rows, header=True, bar=True, sort=False, sort_by=None, mode="table"):
        if len(rows) < 1:
            return
        if isinstance(rows, dict):
            rows = [row for row in rows.values()]

        keys = sorted(rows[0].keys()) if type(rows[0]) is dict else rows[0].keys()
        tbl = Table(*[Column(k, k, rows) for k in keys], mode=mode, auto_header=header, auto_bar=bar, sort=sort, sort_by=sort_by)
        tbl.print_rows(rows)

    @classmethod
    def auto_format_rows(cls, rows, header=True, bar=True, sort=False, sort_by=None, mode="table"):
        if len(rows) < 1:
            return
        if isinstance(rows, dict):
            rows = [row for row in rows.itervalues()]

        keys = sorted(rows[0].keys()) if type(rows[0]) is dict else rows[0].keys()
        tbl = Table(*[Column(k, k, rows) for k in keys], mode=mode, sort=sort, sort_by=sort_by)
        output_rows = tbl.format_rows(rows)
        if header:
            if bar and mode == "table":
                output_rows.insert(0, tbl.header_bar)
            output_rows.insert(0, tbl.header_row)
        return output_rows

    def print_header(self, add_bar=True):
        self.auto_header = False
        if self.mode == "csv":
            self.print_row(self.headers)
        elif self.mode == "table":
            uprint(self.header_row.rstrip())
            if add_bar or self.auto_bar:
                self.print_bar()

    def print_bar(self):
        self.auto_bar = False
        if self.mode == "table":
            uprint(self.header_bar[:term.width])

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
        if self.mode == "csv":
            return self._csv_str(row_dict)
        elif self.mode == "table":
            # Don't str() the row_dict[k] value! That will break type-specific format strings (e.g., int/float)
            row = {k: row_dict[k] if row_dict[k] is not None else "" for k in self.keys}
            try:
                return self.row_fmt.format(row).rstrip()
            except ValueError:
                return self.header_fmt.format(row).rstrip()

    def print_row(self, row_dict, color=None):
        if self.auto_header:
            self.print_header()
        if self.mode == "csv":
            self.csv_writer.writerow({k: row_dict[k] for k in self.keys})
        elif self.mode == "table":
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
                rows = sorted(rows, key=replacement_itemgetter(*sort_by, replacements={None: ""}))
        elif self.sort:
            rows = sorted(rows)

        if self.mode == "csv":
            rows = [{k: row[k] for k in self.keys} for row in rows]
        return rows

    def format_rows(self, rows):
        rows = self.sorted(rows)
        if self.mode == "csv":
            return list(self._csv_str(rows).splitlines())
        elif self.mode == "table":
            return [self.format_row(row) for row in rows]

    def print_rows(self, rows):
        rows = self.sorted(rows)
        if self.update_width:
            for col in self.columns:
                col.width = [row[col.key] for row in rows]

        if self.auto_header:
            self.print_header()
        try:
            if self.mode == "csv":
                self.csv_writer.writerows(rows)
            elif self.mode == "table":
                for row in rows:
                    uprint(self.format_row(row))
        except IOError as e:
            if e.errno == 32:   #broken pipe
                return


def readable_bytes(file_size):
    units = dict(zip(["B ", "KB", "MB", "GB", "TB", "PB"], [0, 2, 2, 2, 2, 2]))
    try:
        exp = min(int(math.log(file_size, 1024)), len(units) - 1) if file_size > 0 else 0
    except TypeError as e:
        print("Invalid file size: '{}'".format(file_size))
        raise e
    unit, dec = units[exp]
    return "{{:,.{}f}} {}".format(dec, unit).format(file_size / 1024 ** exp)


def format_percent(num, div):
    return "{:,.2%}".format(num, div) if div > 0 else "--.--%"


def format_output(text, should_color, color_str, width=None, justify=None):
    """
    Pad output with spaces to work around ansi colors messing with normal string formatting width detection

    :param str text: Text to format
    :param bool should_color: Do apply color_str color
    :param str color_str: Color to use
    :param int width: Column width (for padding)
    :param str justify: Left or Right (default: right)
    :return str: Formatted output
    """
    if width is not None:
        padding = " " * (width - len(text))
        j = justify[0].upper() if justify is not None else "L"
        text = text + padding if j == "L" else padding + text
    if should_color:
        return colored(text, color_str)
    return text


def format_tiered(obj):
    lines = []
    if isinstance(obj, dict):
        if len(obj) < 1:
            return format_tiered("{}")
        kw = max(len(k) for k in obj)
        pad = " " * kw

        key_list = obj.keys() if isinstance(obj, OrderedDict) else sorted(obj.keys())
        for k in key_list:
            fk = k.ljust(kw)
            sub_objs = format_tiered(obj[k])
            for i in range(len(sub_objs)):
                if i == 0:
                    lines.append("{}:  {}".format(fk, sub_objs[i]))
                else:
                    lines.append("{}   {}".format(pad, sub_objs[i]))
    elif isinstance(obj, list):
        if len(obj) < 1:
            return format_tiered("[]")
        kw = len(str(len(obj)))
        pad = " " * kw
        fmt = "[{{:>{}}}]:  {{}}".format(kw)
        for i in range(len(obj)):
            sub_objs = format_tiered(obj[i])
            for j in range(len(sub_objs)):
                if j == 0:
                    lines.append(fmt.format(i, sub_objs[j]))
                else:
                    lines.append(" {}    {}".format(pad, sub_objs[j]))
    else:
        try:
            lines.append(str(obj))
        except Exception as e:
            lines.append(obj)
    return lines


def print_tiered(obj):
    for line in format_tiered(obj):
        uprint(line)


class JSONSetEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, set):
            return sorted(o)
        return super().default(o)


def prep_for_yaml(obj):
    if isinstance(obj, dict):
        return {prep_for_yaml(k): prep_for_yaml(v) for k, v in obj.items()}
    elif isinstance(obj, (list, set)):
        return [prep_for_yaml(v) for v in obj]
    else:
        return obj


class Printer:
    formats = ["json", "json-pretty", "json-compact", "text", "yaml", "pprint", "csv", "table"]

    def __init__(self, output_format):
        if output_format is None or output_format in Printer.formats:
            self.output_format = output_format
        else:
            raise ValueError("Invalid output format: {} (valid options: {})".format(output_format, Printer.formats))

    def pformat(self, content, *args, **kwargs):
        if isinstance(content, types.GeneratorType):
            return "\n".join(self.pformat(c, *args, **kwargs) for c in content)
        elif self.output_format == "json":
            return json.dumps(content, cls=JSONSetEncoder)
        elif self.output_format == "json-pretty":
            return json.dumps(content, sort_keys=True, indent=4, cls=JSONSetEncoder)
        elif self.output_format == "json-compact":
            return json.dumps(content, separators=(",", ":"), cls=JSONSetEncoder)
        elif self.output_format == "text":
            return format_tiered(content)
        elif self.output_format == "yaml":
            content = prep_for_yaml(content)
            if isinstance(content, dict) or kwargs.pop("force_single_yaml", False):
                formatted = yaml.safe_dump(content, explicit_start=True, default_flow_style=False, width=float("inf"), allow_unicode=True)
            else:
                formatted = yaml.safe_dump(content, explicit_start=True, width=float("inf"), allow_unicode=True)
            if formatted.endswith("...\n"):
                formatted = formatted[:-4]
            if formatted.endswith("\n"):
                formatted = formatted[:-1]
            return formatted
        elif self.output_format == "pprint":
            return pprint.pformat(content)
        elif self.output_format in ("csv", "table"):
            kwargs["mode"] = self.output_format
            try:
                return Table.auto_format_rows(content, *args, **kwargs)
            except AttributeError:
                raise ValueError("Invalid content format to be formatted as a {}".format(self.output_format))
        else:
            return content

    def pprint(self, content, *args, gen_empty_error=None, **kwargs):
        if isinstance(content, types.GeneratorType):
            i = 0
            for c in content:
                self.pprint(c, *args, **kwargs)
                i += 1

            if (i == 0) and gen_empty_error:
                log.error(gen_empty_error)
        elif self.output_format == "text":
            print_tiered(content)
        elif self.output_format in ("csv", "table"):
            kwargs["mode"] = self.output_format
            try:
                Table.auto_print_rows(content, *args, **kwargs)
            except AttributeError:
                raise ValueError("Invalid content format to be formatted as a {}".format(self.output_format))
        else:
            uprint(self.pformat(content, *args, **kwargs))
