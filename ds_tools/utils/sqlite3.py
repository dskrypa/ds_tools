"""
Library for reading rows from an SQLite3 DB in a generic dict-like fashion.

.. warning::
    All input is assumed to be trusted.  There is nothing here that would prevent SQL injection attacks.

This can be somewhat useful for viewing the contents of an unfamiliar SQLite3 DB, but I do *not* recommend using it for
creating anything new or writing to an SQLite3 DB.  I would recommend using SQLAlchemy for that.

:author: Doug Skrypa
"""

from __future__ import annotations

import logging
from functools import cached_property
from operator import itemgetter
from pathlib import Path
from sqlite3 import Row, OperationalError, connect
from typing import Iterator, Optional, Union, Mapping, Any, Collection, Iterable

from ..core.itertools import itemfinder
from ..output import Table, Printer

__all__ = ['Sqlite3Database']
log = logging.getLogger(__name__)


class Sqlite3Database:
    """
    None -> NULL, int -> INTEGER, long -> INTEGER, float -> REAL, str -> TEXT, unicode -> TEXT, buffer -> BLOB
    """

    def __init__(self, db_path: Union[str, Path] = None, execute_log_level: int = 9):
        db_path = db_path or ':memory:'
        if db_path != ':memory:':
            db_path = Path(db_path).expanduser().resolve()
            if not db_path.parent.exists():
                db_path.parent.mkdir(parents=True)
            db_path = db_path.as_posix()
        self.db_path = db_path
        self.db = connect(self.db_path)
        self.db.row_factory = Row
        self._tables = {}
        self.execute_log_level = execute_log_level

    def execute(self, *args, **kwargs):
        """
        Auto commit/rollback on exception via with statement
        :return Cursor: Sqlite3 cursor
        """
        with self.db:
            log.log(self.execute_log_level, 'Executing SQL: {}'.format(', '.join(map('"{}"'.format, args))))
            return self.db.execute(*args, **kwargs)

    def create_table(self, name: str, *args, **kwargs):
        """
        :param name: Name of the table to create
        :param args: DBTable positional args
        :param kwargs: DBTable kwargs
        :return DBTable: DBTable object that represents the created table
        """
        if name in self:
            raise KeyError(f'Table {name!r} already exists')
        self._tables[name] = table = DBTable(self, name, *args, **kwargs)
        return table

    def drop_table(self, name: str, vacuum: bool = True):
        """
        Drop the given table from this DB, optionally performing VACUUM to reconstruct the DB, recovering the space that
        was used by the table that was dropped
        :param name: Name of the table to be dropped
        :param vacuum: Perform VACUUM after dropping the table
        """
        del self[name]
        if vacuum:
            self.execute('VACUUM;')

    def __contains__(self, name: str) -> bool:
        return name in self._tables or name in self.table_names

    def __getitem__(self, name: str) -> DBTable:
        try:
            return self._tables[name]
        except KeyError:
            pass
        if name not in self.table_names:
            raise KeyError(f'Table {name!r} does not exist in this DB')
        self._tables[name] = table = DBTable(self, name)
        return table

    def __delitem__(self, name: str):
        if name not in self:
            raise KeyError(name)
        self.execute(f'DROP TABLE "{name}";')
        del self._tables[name]

    def __iter__(self) -> Iterator[DBTable]:
        for table in self.table_names:
            try:
                yield self[table]
            except OperationalError as e:
                log.error(f'Error constructing DBTable wrapper for {table=}: {e}')

    def query(self, query, *args, **kwargs) -> list[dict[str, Any]]:
        """
        :param query: Query string
        :return: Result rows as dicts (key order is guaranteed in Python 3.7+)
        """
        results = self.execute(query, *args, **kwargs)
        if results.description is None:
            raise OperationalError('No Results.')
        return [dict(row) for row in results]

    def iterquery(self, query, *args, **kwargs):
        results = self.execute(query, *args, **kwargs)
        if results.description is None:
            raise OperationalError('No Results.')
        headers = [fields[0] for fields in results.description]
        for row in results:
            yield dict(zip(headers, row))

    def select(
        self,
        columns: Union[str, Collection[str]],
        table: str,
        where_mode: str = 'AND',
        limit: Optional[int] = None,
        **where_args,
    ):
        """
        SELECT $columns FROM $table (WHERE $where);
        :param columns: Column name(s)
        :param table: Table name
        :param where_mode: Mode to apply subsequent WHERE arguments (AND or OR)
        :param limit: A row limit to include in the query
        :param where_args: key=value pairs that need to be matched for data to be returned
        :return list: Result rows
        """
        table_obj = self[table]
        return table_obj.select(columns, where_mode, limit=limit, **where_args)

    @cached_property
    def table_names(self) -> tuple[str]:
        return tuple(self.get_table_names())

    def _table_metadata(self) -> Iterable[Row]:
        return self.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;")

    def get_table_names(self) -> list[str]:
        """
        :return list: Names of tables in this DB
        """
        return [row['name'] for row in self._table_metadata()]

    def get_table_info(self):
        return {row['name']: dict(row) for row in self._table_metadata()}

    def print_all_tables_info(self, only_with_rows: bool = True):
        bar = '=' * 20
        tables = [(table, len(table)) for table in self]
        if only_with_rows:
            tables = [(t, s) for t, s in tables if s]

        for i, (table, size) in enumerate(tables):
            if i:
                print('\n')
            print(f'{bar}  {table.name} ({size:,d} rows) {bar}\n')
            table.print_info()

    def dump_to_json(self, path: Union[str, Path]):
        path = Path(path).expanduser().resolve() if isinstance(path, str) else path
        if path.is_file():
            raise ValueError(f'Invalid path - must be a directory: {path}')
        elif not path.exists():
            path.mkdir(parents=True)

        printer = Printer('pseudo-json')
        for table in self:
            table_path = path.joinpath(f'{table.name}.json')
            log.info(f'Dumping {table.name} to {table_path}')
            with table_path.open('w', encoding='utf-8') as f:
                f.write(printer.pformat(table.select('*')))

    def test(self):
        tbl1 = self.create_table('test_1', [('id', 'INTEGER'), ('name', 'TEXT')])
        self.create_table('test_2', [('email', 'TEXT'), ('name', 'TEXT')])
        tbl1.insert([0, 'hello db'])
        self['test_2'].insert(['bob@gmail.com', 'bob'])
        self['test_1'].insert([1, 'line2'])


class DBRow(dict):
    __slots__ = ('table', 'pk')

    def __init__(self, db_table, *args, **kwargs):
        """
        :param DBTable db_table: DBTable in which this row resides
        :param args: dict positional args
        :param kwargs: dict kwargs
        """
        self.table = None
        super(DBRow, self).__init__(*args, **kwargs)
        self.table = db_table
        self.pk = self.table.pk

    def __setitem__(self, key, value):
        if self.table is None:
            super(DBRow, self).__setitem__(key, value)
            return

        if (key in self) and (self[key] == value):
            return
        elif key == self.pk:
            raise KeyError('Unable to change PrimaryKey ({!r})'.format(self.pk))
        elif key not in self:
            raise KeyError('Unable to add additional key: {}'.format(key))
        self.table.db.execute('UPDATE "{}" SET "{}" = ? WHERE "{}" = ?;'.format(self.table.name, key, self.pk), (value, self[self.pk]))
        super(DBRow, self).__setitem__(key, value)

    def popitem(self, *args, **kwargs):
        raise NotImplementedError('popitem is not permitted on DBRow objects')

    def pop(self, k, d=None):
        raise NotImplementedError('pop is not permitted on DBRow objects')

    def clear(self):
        raise NotImplementedError('clear is not permitted on DBRow objects')

    def __delitem__(self, *args, **kwargs):
        raise NotImplementedError('del is not permitted on DBRow objects')


class DBTable:
    __slots__ = ('db', 'name', '_rows', 'col_names', 'col_types', 'columns', 'pk', 'pk_pos')
    db: Sqlite3Database

    def __init__(self, parent_db: Sqlite3Database, name: str, columns=None, pk=None):
        """
        :param parent_db: DB in which this table resides
        :param name: Name of the table
        :param list columns: Column names
        :param pk: Primary key (defaults to the table's PK or the first column if not defined for the table)
        """
        self.db = parent_db
        self.name = name
        self._rows = {}
        if table_exists := self.name in self.db:
            table_info = self.info()
            current_names = [entry['name'] for entry in table_info]
            current_types = [entry['type'] for entry in table_info]
            pk_entry = itemfinder(table_info, itemgetter('pk'))
            current_pk = pk_entry['name'] if pk_entry is not None else None
        elif columns is None:
            raise ValueError('Columns are required for tables that do not already exist')
        else:
            current_names, current_types, current_pk = None, None, None

        if columns is not None:
            self.col_names, self.col_types = _normalize_new_columns(columns, current_names, current_types)
        else:
            self.col_names, self.col_types = current_names, current_types

        self.columns = dict(zip(self.col_names, self.col_types))

        if pk is not None:
            if pk not in self.col_names:
                raise ValueError(f'The provided PK {pk!r} is not a column in this table')
            self.pk = pk
        else:
            self.pk = current_pk if current_pk is not None else self.col_names[0]

        self.pk_pos = 0
        for c in range(len(self.col_names)):
            if self.pk == self.col_names[c]:
                self.pk_pos = c
                break
        assert self.col_names[self.pk_pos] == self.pk

        if not table_exists:
            col_strs = [f'{cname} {ctype}' if ctype else cname for cname, ctype in self.columns.items()]
            if pk is not None:
                col_strs[self.pk_pos] += ' PRIMARY KEY'
            self.db.execute(f'CREATE TABLE "{self.name}" ({", ".join(col_strs)});')

    def info(self):
        return self.db.query(f'pragma table_info("{self.name}")')

    def print_info(self):
        Table.auto_print_rows(self.info())

    def _prepare_select_where(self, where_map: Mapping[str, Any], mode: str = 'AND') -> tuple[str, list[str]]:
        if mode not in ('AND', 'OR'):
            raise ValueError(f'Unexpected WHERE {mode=}')
        keys, vals = [], []
        for key, val in where_map.items():
            if key not in self.col_names:
                raise ValueError(f'Invalid WHERE clause: {key!r}={val!r} - invalid column name')
            keys.append(f'{_quote(key)}=?')
            vals.append(val)

        where = f' {mode} '.join(keys)
        return where, vals

    def _prepare_select_what(self, columns: Union[str, Collection[str]]) -> str:
        if isinstance(columns, str):
            if columns == '*':
                return columns
            columns = (columns,)
        if bad := ', '.join(map(repr, (c for c in columns if c not in self.col_names))):
            raise ValueError(f'Invalid columns: {bad}')
        return ', '.join(f'{_quote(c)}' for c in columns)

    def select(
        self, columns: Union[str, Collection[str]] = '*', where_mode: str = 'AND', limit: int = None, **where_args
    ):
        what = self._prepare_select_what(columns)
        where, params = self._prepare_select_where(where_args, where_mode)
        query = f'SELECT {what} FROM {_quote(self.name)}'
        if where:
            query += f' WHERE {where}'
        if limit is not None and isinstance(limit, int):
            query += f' LIMIT {limit}'
        return self.db.query(query, params)

    def print_rows(self, limit=3, out_fmt='table'):
        rows = self.select('*', limit=limit)
        if out_fmt == 'table':
            Table.auto_print_rows(rows)
        else:
            Printer(out_fmt).pprint(rows)

    def insert(self, row):
        if isinstance(row, dict):
            row = [row[k] for k in self.col_names]
        self.db.execute('INSERT INTO "{}" VALUES ({});'.format(self.name, ('?,' * len(row))[:-1]), tuple(row))

    def __len__(self):
        return next(self.db.execute(f'SELECT COUNT(*) FROM "{self.name}"'))[0]

    def __contains__(self, item) -> bool:
        if item in self._rows:
            return True
        where, params = self._prepare_select_where({self.pk: item})
        c = self.db.execute(f'SELECT COUNT(*) AS count FROM "{self.name}" WHERE {where}', params)
        return bool(next(c)['count'])

    def rows(self) -> list[DBRow]:
        return [row for row in self]

    def __iter__(self) -> Iterator[DBRow]:
        for row in self.select('*'):
            pk = row[self.pk]
            self._rows[pk] = db_row = DBRow(self, row)
            yield db_row

    iterrows = __iter__

    def __getitem__(self, item) -> DBRow:
        try:
            return self._rows[item]
        except KeyError:
            pass
        results = self.select('*', **{self.pk: item})
        if not results:
            raise KeyError(item)
        self._rows[item] = row = DBRow(self, results[0])
        return row

    def __delitem__(self, key):
        if key not in self:
            raise KeyError(key)
        self.db.execute(f'DELETE FROM "{self.name}" WHERE "{self.pk}" = ?;', (key,))
        del self._rows[key]

    def __setitem__(self, key, value):
        """
        Replace a current row, or insert a new one.  If a list or tuple is provided and its length is 1 shorter than the
        number of columns in this table, then the PK is inserted at position self.pk_pos before the row is modified.
        :param key: PK of a row in this table
        :param value: list, tuple, or dict to be added to this table
        """
        if not isinstance(value, (list, dict, tuple)):
            raise TypeError('Rows must be provided as a list, tuple, or dict, not {}'.format(type(value)))

        col_count = len(self.col_names)
        if len(value) not in (col_count, col_count - 1):
            raise ValueError('Invalid number of elements in the provided row: {}'.format(len(value)))

        if key in self:
            if isinstance(value, dict):
                row = value
            else:
                row_list = list(value)
                if len(value) != col_count:
                    row_list.insert(self.pk_pos, key)
                row = dict(zip(self.col_names, row_list))
            self[key].update(row)
        else:
            if isinstance(value, dict):
                val_pk = value.get(self.pk, None)
                if val_pk is None:
                    row = dict(**value)
                    row[self.pk] = key
                elif val_pk != key:
                    raise KeyError('The PK {!r} does not match the value in the provided row: {}'.format(key, val_pk))
                else:
                    row = value
            else:
                row = list(value)
                if len(value) != col_count:
                    row.insert(self.pk_pos, key)
            self.insert(row)


def _normalize_new_columns(columns, current_names, current_types):
    if not isinstance(columns, (list, tuple)):
        raise TypeError(f'Columns must be provided as a list or tuple, not {type(columns)}')
    elif (current_names is not None) and (len(current_names) != len(columns)):
        raise ValueError('The number of columns provided does not match the existing ones')

    col_names, col_types = [], []
    for col in columns:
        if isinstance(col, tuple):
            col_names.append(col[0])
            col_types.append(col[1])
        else:
            col_names.append(col)
            col_types.append('')

    if (current_names is not None) and (col_names != current_names):
        raise ValueError('The provided column names do not match the existing ones')
    elif current_types is not None:
        for i in range(len(current_types)):
            ct = current_types[i]
            nt = col_types[i]
            if (ct != nt) and ((ct != '') or (nt != '')):
                raise ValueError(
                    f'The provided type={ct!r} for column={col_names[i]!r} did not match the existing type={nt!r}'
                )
    return col_names, col_types


def _quote(name: str) -> str:
    if ' ' in name:
        return f'"{name}"'
    return name
