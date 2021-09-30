"""
Dict-like cache classes to be used with the :func:`cached<.caching.decorate.cached>` decorator.

:author: Doug Skrypa
"""

import json
import logging
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from urllib.parse import urlencode, quote as url_quote
from typing import Union, Callable, Iterator, Any

__all__ = ['FSCache']
log = logging.getLogger(__name__)


class FSCache:
    def __init__(
        self,
        cache_dir: Union[str, Path] = None,
        cache_subdir: str = None,
        prefix: str = None,
        ext: str = 'txt',
        dumper: Callable = None,
        loader: Callable = None,
        binary: bool = False,
    ):
        from threading import RLock
        from ..fs.paths import validate_or_make_dir, get_user_cache_dir

        if cache_dir:
            self.cache_dir = Path(cache_dir).joinpath(cache_subdir) if cache_subdir else Path(cache_dir)
            validate_or_make_dir(self.cache_dir)
        else:
            self.cache_dir = get_user_cache_dir(cache_subdir)
        self.prefix = prefix or ''
        self._ext = ext
        self.dumper = dumper
        self.loader = loader
        self.binary = binary
        self._lock = RLock()

    @property
    def ext(self) -> str:
        return ('.' + self._ext) if self._ext else ''

    @property
    def read_mode(self) -> str:
        return 'rb' if self.binary else 'r'

    @property
    def write_mode(self) -> str:
        return 'wb' if self.binary else 'w'

    def filename_for_key(self, key: str) -> str:
        return '{}{}{}'.format(self.prefix, key, self.ext)

    def path_for_key(self, key: str) -> Path:
        return self.cache_dir.joinpath(f'{self.prefix}{key}{self.ext}')

    @classmethod
    def _html_key_with_extras(cls, key, kwargs) -> str:
        extras = {}
        for arg, name in (('params', 'query'), ('data', 'data'), ('json', 'json')):
            if value := kwargs.get(arg):
                if hasattr(value, 'items'):
                    value = sorted(value.items())
                # key += '__{}__{}'.format(name, urlencode(value, True))
                extras[name] = urlencode(value, True)
        if extras:  # Without the below hash, the extras could result in filenames that were too large
            key += '__' + sha256(json.dumps(extras, sort_keys=True).encode('utf-8')).hexdigest()
        return key

    @classmethod
    def html_key(cls, self, endpoint, *args, **kwargs) -> str:
        key = '{}__{}'.format(self.host, endpoint.replace('/', '_'))
        return cls._html_key_with_extras(key, kwargs)

    @classmethod
    def html_key_nohost(cls, self, endpoint, *args, **kwargs) -> str:
        key = endpoint.replace('/', '_')
        return cls._html_key_with_extras(key, kwargs)

    @classmethod
    def dated_html_key_func(cls, date_fmt: str = '%Y-%m-%d', include_host: bool = True) -> Callable:
        def key_func(self, endpoint, *args, **kwargs):
            if include_host:
                return '{}__{}__{}'.format(self.host, datetime.now().strftime(date_fmt), url_quote(endpoint, ''))
            else:
                return '{}__{}'.format(datetime.now().strftime(date_fmt), url_quote(endpoint, ''))
        return key_func

    @classmethod
    def dated_html_key(cls, self, endpoint, *args, **kwargs) -> str:
        return '{}__{}__{}'.format(self.host, datetime.now().strftime('%Y-%m-%d'), url_quote(endpoint, ''))

    @classmethod
    def dated_html_key_nohost(cls, self, endpoint, *args, **kwargs) -> str:
        return '{}__{}'.format(datetime.now().strftime('%Y-%m-%d'), url_quote(endpoint, ''))

    def keys(self) -> list[str]:
        with self._lock:
            p_len = len(self.prefix)
            keys = [
                f[p_len:]
                for p in self.cache_dir.iterdir()
                if p.is_file() and (f := p.stem) and p.suffix == self.ext and f.startswith(self.prefix)
            ]
            return keys

    def values(self) -> list[Any]:
        with self._lock:
            return [self[key] for key in self.keys()]

    def items(self) -> Iterator[tuple[str, Any]]:
        with self._lock:
            return zip(self.keys(), self.values())

    def __getitem__(self, item: str) -> Any:
        file_path = self.path_for_key(item)
        if not (file_path.exists() and file_path.is_file()):
            log.log(9, 'No cached value existed for {!r} at {!r}'.format(item, file_path.as_posix()))
            raise KeyError(item)

        kwargs = {} if self.binary else {'encoding': 'utf-8'}
        with file_path.open(self.read_mode, **kwargs) as f:
            value = f.read()

        log.log(9, 'Returning value for {!r} from {!r}'.format(item, file_path.as_posix()))
        return self.loader(value) if self.loader else value

    def __setitem__(self, key: str, value: Any):
        file_path = self.path_for_key(key)
        if self.dumper:
            value = self.dumper(value)

        kwargs = {} if self.binary else {'encoding': 'utf-8'}
        log.log(9, 'Storing value for {!r} in {!r}'.format(key, file_path.as_posix()))
        with file_path.open(self.write_mode, **kwargs) as f:
            f.write(value)
