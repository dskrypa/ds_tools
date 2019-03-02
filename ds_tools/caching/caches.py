"""
Dict-like cache classes to be used with the :func:`cached<.caching.decorate.cached>` decorator.

:author: Doug Skrypa
"""

import logging
import os
from pathlib import Path
from urllib.parse import urlencode, quote as url_quote

from sqlalchemy import create_engine, MetaData, Table, Column, PickleType
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm.exc import NoResultFound
from sqlalchemy.exc import NoSuchTableError, OperationalError
from wrapt import synchronized

from ..core import validate_or_make_dir, get_user_cache_dir, ScopedSession, now

__all__ = ['DBCache', 'DBCacheEntry', 'FSCache']
log = logging.getLogger(__name__)

Base = declarative_base()


class FSCache:
    def __init__(self, cache_dir=None, cache_subdir=None, prefix=None, ext='txt', dumper=None, loader=None, binary=False):
        if cache_dir:
            self.cache_dir = os.path.join(cache_dir, cache_subdir) if cache_subdir else cache_dir
            validate_or_make_dir(self.cache_dir)
        else:
            self.cache_dir = get_user_cache_dir(cache_subdir)
        self.prefix = prefix or ''
        self._ext = ext
        self.dumper = dumper
        self.loader = loader
        self.binary = binary

    @property
    def ext(self):
        return ('.' + self._ext) if self._ext else ''

    @property
    def read_mode(self):
        return 'rb' if self.binary else 'r'

    @property
    def write_mode(self):
        return 'wb' if self.binary else 'w'

    def filename_for_key(self, key):
        return '{}{}{}'.format(self.prefix, key, self.ext)

    def path_for_key(self, key):
        return Path(os.path.join(self.cache_dir, '{}{}{}'.format(self.prefix, key, self.ext)))

    @classmethod
    def _html_key_with_extras(cls, key, kwargs):
        for arg, name in (('params', 'query'), ('data', 'data'), ('json', 'json')):
            value = kwargs.get(arg)
            if value:
                if hasattr(value, 'items'):
                    value = sorted(value.items())
                key += '__{}__{}'.format(name, urlencode(value, True))
        return key

    @classmethod
    def html_key(cls, self, endpoint, *args, **kwargs):
        key = '{}__{}'.format(self.host, endpoint.replace('/', '_'))
        return cls._html_key_with_extras(key, kwargs)

    @classmethod
    def html_key_nohost(cls, self, endpoint, *args, **kwargs):
        key = endpoint.replace('/', '_')
        return cls._html_key_with_extras(key, kwargs)

    @classmethod
    def dated_html_key_func(cls, date_fmt='%Y-%m-%d', include_host=True):
        def key_func(self, endpoint, *args, **kwargs):
            if include_host:
                return '{}__{}__{}'.format(self.host, now(date_fmt), url_quote(endpoint, ''))
            else:
                return '{}__{}'.format(now(date_fmt), url_quote(endpoint, ''))
        return key_func

    @classmethod
    def dated_html_key(cls, self, endpoint, *args, **kwargs):
        return '{}__{}__{}'.format(self.host, now('%Y-%m-%d'), url_quote(endpoint, ''))

    @classmethod
    def dated_html_key_nohost(cls, self, endpoint, *args, **kwargs):
        return '{}__{}'.format(now('%Y-%m-%d'), url_quote(endpoint, ''))

    @synchronized
    def keys(self):
        p_len = len(self.prefix)
        e_len = len(self.ext)
        keys = [
            f[p_len:-e_len] for f in os.listdir(self.cache_dir) if f.startswith(self.prefix) and f.endswith(self.ext)
        ]
        return keys

    @synchronized
    def values(self):
        return [self[key] for key in self.keys()]

    @synchronized
    def items(self):
        return zip(self.keys(), self.values())

    def __getitem__(self, item):
        file_path = self.path_for_key(item)
        if not (file_path.exists() and file_path.is_file()):
            log.log(9, 'No cached value existed for {!r} at {!r}'.format(item, file_path.as_posix()))
            raise KeyError(item)

        kwargs = {} if self.binary else {'encoding': 'utf-8'}
        with open(file_path.as_posix(), self.read_mode, **kwargs) as f:
            value = f.read()

        log.log(9, 'Returning value for {!r} from {!r}'.format(item, file_path.as_posix()))
        return self.loader(value) if self.loader else value

    def __setitem__(self, key, value):
        file_path = self.path_for_key(key)
        if self.dumper:
            value = self.dumper(value)

        kwargs = {} if self.binary else {'encoding': 'utf-8'}
        log.log(9, 'Storing value for {!r} in {!r}'.format(key, file_path.as_posix()))
        with open(file_path.as_posix(), self.write_mode, **kwargs) as f:
            f.write(value)


class DBCacheEntry(Base):
    """A key, value pair for use in :class:`DBCache`"""
    __tablename__ = 'cache'

    key = Column(PickleType, primary_key=True)
    value = Column(PickleType)

    def __repr__(self):
        return '<{}({!r})>'.format(type(self).__name__, self.key)


class DBCache:
    """
    A dictionary-like cache that stores values in an SQLite3 DB.  Old cache files in the cache directory that begin with
    the same ``file_prefix`` and username that have non-matching dates in their filename will be deleted when a cache
    file with a new date is created (unless preserve_old is set to True).

    Based on the args provided and the current user, the final path will be: ``db_dir/file_prefix.user.timestamp.db``

    :param str file_prefix: Prefix for DB cache file names
    :param str time_fmt: Datetime format to use for DB cache file names
    :param str|None db_dir: Directory in which DB cache files should be stored; default: result of
      :func:`get_user_cache_dir<ds_tools.utils.filesystem.get_user_cache_dir>`
    :param bool preserve_old: True to preserve old cache files, False (default) to delete them
    """
    def __init__(self, prefix, cache_dir=None, cache_subdir=None, time_fmt='%Y-%m', preserve_old=False, db_path=None):
        if not db_path:
            if cache_dir:
                self.cache_dir = os.path.join(cache_dir, cache_subdir) if cache_subdir else cache_dir
                validate_or_make_dir(self.cache_dir)
            else:
                self.cache_dir = get_user_cache_dir(cache_subdir)
            db_file_prefix = '{}.'.format(prefix)
            current_db = '{}{}.db'.format(db_file_prefix, now(time_fmt))

            if not preserve_old:
                for fname in os.listdir(self.cache_dir):
                    if fname.startswith(db_file_prefix) and fname.endswith('.db') and fname != current_db:
                        file_path = os.path.join(self.cache_dir, fname)
                        try:
                            if os.path.isfile(file_path):
                                log.debug('Deleting old cache file: {}'.format(file_path))
                                os.remove(file_path)
                        except OSError as e:
                            log.debug('{} while deleting old cache file {}: {}'.format(type(e).__name__, file_path, e))

            db_path = os.path.join(self.cache_dir, current_db)
        else:
            _path = Path(db_path).expanduser().resolve()
            if not _path.exists():
                os.makedirs(_path.parent.as_posix())

        self.engine = create_engine('sqlite:///{}'.format(db_path), echo=False)
        self.meta = MetaData(self.engine)
        try:
            self.table = Table(DBCacheEntry.__tablename__, self.meta, autoload=True)
        except NoSuchTableError as e:
            Base.metadata.create_all(self.engine)
            self.table = Table(DBCacheEntry.__tablename__, self.meta, autoload=True)
        self.db_session = ScopedSession(self.engine)

    def keys(self):
        with self.db_session as session:
            for entry in session.query(DBCacheEntry):
                yield entry.key

    def values(self):
        with self.db_session as session:
            for entry in session.query(DBCacheEntry):
                yield entry.value

    def items(self):
        with self.db_session as session:
            for entry in session.query(DBCacheEntry):
                yield entry.key, entry.value

    def get(self, item, default=None):
        try:
            return self[item]
        except KeyError:
            return default

    def __getitem__(self, item):
        with synchronized(self):
            with self.db_session as session:
                try:
                    return session.query(DBCacheEntry).filter_by(key=item).one().value
                except (NoResultFound, OperationalError) as e:
                    raise KeyError(item) from e

    def __setitem__(self, key, value):
        with synchronized(self):
            with self.db_session as session:
                entry = DBCacheEntry(key=key, value=value)
                session.merge(entry)
                session.commit()

    def __delitem__(self, key):
        with synchronized(self):
            with self.db_session as session:
                try:
                    session.query(DBCacheEntry).filter_by(key=key).delete()
                except (NoResultFound, OperationalError) as e:
                    raise KeyError(key) from e
                else:
                    session.commit()
