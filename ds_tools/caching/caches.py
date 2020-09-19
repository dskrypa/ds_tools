"""
Dict-like cache classes to be used with the :func:`cached<.caching.decorate.cached>` decorator.

:author: Doug Skrypa
"""

import logging
import os
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode, quote as url_quote

__all__ = ['FSCache']
log = logging.getLogger(__name__)


class FSCache:
    def __init__(
        self, cache_dir=None, cache_subdir=None, prefix=None, ext='txt', dumper=None, loader=None, binary=False
    ):
        from threading import RLock
        if cache_dir:
            from ..fs.paths import validate_or_make_dir
            self.cache_dir = os.path.join(cache_dir, cache_subdir) if cache_subdir else cache_dir
            validate_or_make_dir(self.cache_dir)
        else:
            from ..fs.paths import get_user_cache_dir
            self.cache_dir = get_user_cache_dir(cache_subdir)
        self.prefix = prefix or ''
        self._ext = ext
        self.dumper = dumper
        self.loader = loader
        self.binary = binary
        self._lock = RLock()

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
                return '{}__{}__{}'.format(self.host, datetime.now().strftime(date_fmt), url_quote(endpoint, ''))
            else:
                return '{}__{}'.format(datetime.now().strftime(date_fmt), url_quote(endpoint, ''))
        return key_func

    @classmethod
    def dated_html_key(cls, self, endpoint, *args, **kwargs):
        return '{}__{}__{}'.format(self.host, datetime.now().strftime('%Y-%m-%d'), url_quote(endpoint, ''))

    @classmethod
    def dated_html_key_nohost(cls, self, endpoint, *args, **kwargs):
        return '{}__{}'.format(datetime.now().strftime('%Y-%m-%d'), url_quote(endpoint, ''))

    def keys(self):
        with self._lock:
            p_len = len(self.prefix)
            e_len = len(self.ext)
            keys = [
                f[p_len:-e_len]
                for f in os.listdir(self.cache_dir)
                if f.startswith(self.prefix) and f.endswith(self.ext)
            ]
            return keys

    def values(self):
        with self._lock:
            return [self[key] for key in self.keys()]

    def items(self):
        with self._lock:
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
