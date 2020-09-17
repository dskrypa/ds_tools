"""
Library for reading rows from an SQLite3 DB in a generic dict-like fashion.

All input is assumed to be trusted.  There is nothing here that would prevent SQL injection attacks.

This can be somewhat useful for viewing the contents of an unfamiliar SQLite3 DB, but I do not recommend using it for
creating anything new or writing to an SQLite3 DB.  I would recommend using SQLAlchemy for that.

:author: Doug Skrypa
"""

import os
import sqlite3
import logging
from operator import itemgetter
from pathlib import Path
from typing import Iterator, Optional, List, Union

from ..core import itemfinder
from ..output import Table, Printer

__all__ = ['Sqlite3Database']
log = logging.getLogger(__name__)
OperationalError = sqlite3.OperationalError


class Sqlite3Database:
    """
    None -> NULL, int -> INTEGER, long -> INTEGER, float -> REAL, str -> TEXT, unicode -> TEXT, buffer -> BLOB
    """
    def __init__(self, db_path=None):
        self.db_path = os.path.expanduser(db_path if db_path is not None else ':memory:')
        if self.db_path != ':memory:':
            db_dir = os.path.dirname(self.db_path)
            if not os.path.exists(db_dir):
                os.makedirs(db_dir)
        self.db = sqlite3.connect(self.db_path)
        self._tables = {}

    def execute(self, *args, **kwargs):
        """
        Auto commit/rollback on exception via with statement
        :return Cursor: Sqlite3 cursor
        """
        with self.db:
            log.log(9, 'Executing SQL: {}'.format(', '.join(map('"{}"'.format, args))))
            return self.db.execute(*args, **kwargs)

    def create_table(self, name, *args, **kwargs):
        """
        :param name: Name of the table to create
        :param args: DBTable positional args
        :param kwargs: DBTable kwargs
        :return DBTable: DBTable object that represents the created table
        """
        if name in self:
            raise KeyError('{} already exists'.format(name))
        self._tables[name] = DBTable(self, name, *args, **kwargs)
        return self._tables[name]

    def drop_table(self, name, vacuum=True):
        """
        Drop the given table from this DB, optionally performing VACUUM to reconstruct the DB, recovering the space that
        was used by the table that was dropped
        :param name: Name of the table to be dropped
        :param bool vacuum: Perform VACUUM after dropping the table
        """
        del self[name]
        if vacuum:
            self.execute('VACUUM;')

    def __contains__(self, item):
        if item in self._tables:
            return True
        return item in self.get_table_names()

    def __getitem__(self, item) -> 'DBTable':
        if item not in self._tables:
            if item not in self:
                raise KeyError('Table {!r} does not exist in this DB'.format(item))
            self._tables[item] = DBTable(self, item)
        return self._tables[item]

    def __delitem__(self, key):
        if key in self:
            self.execute('DROP TABLE "{}";'.format(key))
            del self._tables[key]
        else:
            raise KeyError(key)

    def __iter__(self) -> Iterator['DBTable']:
        for table in sorted(self.get_table_names()):
            try:
                yield self[table]
            except OperationalError as e:
                log.error(f'Error constructing DBTable wrapper for {table=!r}: {e}')

    def query(self, query, *args, **kwargs):
        """
        :param query: Query string
        :return list: Result rows as dicts (key order is guaranteed in Python 3.7+)
        """
        results = self.execute(query, *args, **kwargs)
        if results.description is None:
            raise OperationalError('No Results.')
        headers = [fields[0] for fields in results.description]
        return [dict(zip(headers, row)) for row in results]

    def iterquery(self, query, *args, **kwargs):
        results = self.execute(query, *args, **kwargs)
        if results.description is None:
            raise OperationalError('No Results.')
        headers = [fields[0] for fields in results.description]
        for row in results:
            yield dict(zip(headers, row))

    def select(self, columns, table, where_mode='AND', limit: Optional[int] = None, **where_args):
        """
        SELECT $columns FROM $table (WHERE $where);
        :param columns: Column name(s)
        :param table: Table name
        :param where_mode: Mode to apply subsequent WHERE arguments (AND or OR)
        :param limit: A row limit to include in the query
        :param where_args: key=value pairs that need to be matched for data to be returned
        :return list: Result rows
        """
        if table not in self:
            raise KeyError(table)
        elif where_mode not in ('AND', 'OR'):
            raise ValueError('Invalid where mode: {}'.format(where_mode))
        cols = ', '.join(columns) if isinstance(columns, (list, tuple)) else columns
        where_clip = (len(where_mode) + 2) * -1
        where = ('? = ? {} '.format(where_mode) * len(where_args))[:where_clip] if len(where_args) > 0 else ''
        where_list = []
        for k, v in where_args.items():
            where_list.append(k)
            where_list.append(v)
        suffix = ' WHERE ' + where if where else ''
        if limit and isinstance(limit, int):
            suffix += f' LIMIT {limit}'
        return self.query('SELECT {} FROM "{}"{};'.format(cols, table, suffix), tuple(where_list))

    def get_table_names(self) -> List[str]:
        """
        :return list: Names of tables in this DB
        """
        return [row['name'] for row in self.query('SELECT name FROM sqlite_master WHERE type=\'table\';')]

    def get_table_info(self):
        return {row['name']: row for row in self.query('SELECT * FROM sqlite_master WHERE type=\'table\';')}

    def print_all_tables_info(self, only_with_rows=True):
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
    def __init__(self, parent_db, name, columns=None, pk=None):
        """
        :param AbstractDB parent_db: DB in which this table resides
        :param name: Name of the table
        :param list columns: Column names
        :param pk: Primary key (defaults to the table's PK or the first column if not defined for the table)
        """
        self.db = parent_db  # type: Sqlite3Database
        self.name = name
        self._rows = {}
        table_exists = self.name in self.db

        if (columns is None) and (not table_exists):
            raise ValueError('Columns are required for tables that do not already exist')

        if table_exists:
            table_info = self.info()
            current_names = [entry['name'] for entry in table_info]
            current_types = [entry['type'] for entry in table_info]
            pk_entry = itemfinder(table_info, itemgetter('pk'))
            current_pk = pk_entry['name'] if pk_entry is not None else None
        else:
            current_names, current_types, current_pk = None, None, None

        if columns is not None:
            if not isinstance(columns, (list, tuple)):
                raise TypeError('Columns must be provided as a list or tuple, not {}'.format(type(columns)))
            elif (current_names is not None) and (len(current_names) != len(columns)):
                raise ValueError('The number of columns provided does not match the existing ones')

            self.col_names, self.col_types = [], []
            for col in columns:
                if isinstance(col, tuple):
                    self.col_names.append(col[0])
                    self.col_types.append(col[1])
                else:
                    self.col_names.append(col)
                    self.col_types.append('')

            if (current_names is not None) and (self.col_names != current_names):
                raise ValueError('The provided column names do not match the existing ones')
            elif current_types is not None:
                for i in range(len(current_types)):
                    ct = current_types[i]
                    nt = self.col_types[i]
                    if (ct != nt) and ((ct != '') or (nt != '')):
                        raise ValueError('The provided type for column {!r} ({}) did not match the existing one ({})'.format(self.col_names[i], ct, nt))
        else:
            self.col_names = current_names
            self.col_types = current_types

        self.columns = dict(zip(self.col_names, self.col_types))

        if pk is not None:
            if pk not in self.col_names:
                raise ValueError('The provided PK {!r} is not a column in this table'.format(pk))
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
            col_strs = ['{} {}'.format(cname, ctype) if ctype else cname for cname, ctype in self.columns.items()]
            if pk is not None:
                col_strs[self.pk_pos] += ' PRIMARY KEY'
            self.db.execute('CREATE TABLE "{}" ({});'.format(self.name, ', '.join(col_strs)))

    def info(self):
        return self.db.query('pragma table_info("{}")'.format(self.name))

    def print_info(self):
        Table.auto_print_rows(self.info())

    def select(self, columns, where_mode='AND', limit=None, **where_args):
        return self.db.select(columns, self.name, where_mode, limit=limit, **where_args)

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

    def __contains__(self, item):
        if item in self._rows:
            return True
        return bool(self.select('*', **{self.pk: item}))

    def rows(self):
        return [row for row in iter(self)]

    def __iter__(self):
        for row in self.select('*'):
            pk = row[self.pk]
            if pk not in self._rows:
                self._rows[pk] = DBRow(self, row)
            yield self._rows[pk]

    iterrows = __iter__

    def __getitem__(self, item):
        if item not in self._rows:
            results = self.select('*', **{self.pk: item})
            if not results:
                raise KeyError(item)
            self._rows[item] = DBRow(self, results[0])
        return self._rows[item]

    def __delitem__(self, key):
        if key in self:
            self.db.execute('DELETE FROM "{}" WHERE "{}" = ?;'.format(self.name, self.pk), (key,))
            del self._rows[key]
        else:
            raise KeyError(key)

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
