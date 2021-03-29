import logging
from abc import ABC, abstractmethod
from base64 import b64decode
from functools import cached_property
from typing import TYPE_CHECKING, Dict, Optional, Tuple, Any
from urllib.parse import urlparse

from requests import RequestException, Response

from .utils import Retries

if TYPE_CHECKING:
    from .m3u import EXTM3U
    from .stream import VideoStream

__all__ = ['M3USegment', 'FileSegment', 'KeySegment', 'MediaSegment']
log = logging.getLogger(__name__)


class M3USegment:
    def __init__(self, ext_m3u: 'EXTM3U', n: int, line: str, info: Optional[Dict[str, str]] = None):
        self.ext_m3u = ext_m3u
        self._n = n
        self._line = line
        self.info = info

    def __str__(self):
        # TODO: If this is a crypto key segment, retrieve it, or fix the url if necessary
        # key: may be b64 encoded
        return self._line + '\n'

    def __repr__(self):
        return f'<{self.__class__.__name__}[{self._n}: {self._line}]>'

    @property
    def stream(self) -> 'VideoStream':
        return self.ext_m3u.stream

    def __lt__(self, other: 'M3USegment') -> bool:
        return self._n < other._n

    def __eq__(self, other: 'M3USegment') -> bool:
        return self.ext_m3u == other.ext_m3u and self._n == other._n


class FileSegment(M3USegment, ABC):
    def __repr__(self):
        return f'<{self.__class__.__name__}[{self._n}: {self.name}]>'

    @property
    @abstractmethod
    def file_name(self) -> Optional[str]:
        return NotImplemented

    @property
    @abstractmethod
    def name(self) -> Optional[str]:
        return NotImplemented

    @property
    @abstractmethod
    def url(self) -> Optional[str]:
        return NotImplemented

    @cached_property
    def path(self):
        return self.stream.temp_dir_path.joinpath(self.file_name)

    def _get(self, headers: Optional[Dict[str, Any]] = None) -> Response:
        exc = None
        for t in Retries():
            try:
                resp = self.stream.session.get(self.url, headers=headers)
                resp.raise_for_status()
            except RequestException as e:
                exc = e
                log.error(f'\nError retrieving {self!r}, will sleep {t}s: {e}')
                if self.stream._exiting.wait(t):
                    log.warning(f'\nGiving up on {self!r} due to exit event')
                    raise
                log.info(f'\nRetrying {self!r}...')
            else:
                return resp

        log.critical(f'\nUnable to retrieve {self!r}')
        if exc is None:
            raise RuntimeError(f'Unable to retrieve {self!r} and no HTTP exception was captured')
        raise exc

    get = _get

    def save(self, content: bytes):
        log.debug(f'Writing {self.file_name}')
        if not self.path.parent.exists():
            self.path.parent.mkdir(parents=True)
        with self.path.open('wb') as f:
            f.write(content)


class KeySegment(FileSegment):
    def __str__(self):
        info = '\n'.join(f'#{key}:{value}' for key, value in self.info.items())
        return f'{info}\n{self.file_name}\n' if info else f'{self.file_name}\n'

    @cached_property
    def _uri(self) -> Optional[str]:
        if 'METHOD=NONE' in self._line:
            return None
        elif uri := next((part for part in self._line.split(',') if part.startswith('URI=')), None):
            return uri.split('=', 1)[1].strip('"')
        return None

    @cached_property
    def name(self) -> Optional[str]:
        if uri := self._uri:
            if uri.startswith(('http://', 'https://')):
                return urlparse(uri).path.rsplit('/', 1)[-1]  # noqa
            elif '/' in uri:
                base, name = uri.rsplit('/', 1)
                if base and self.stream.m3u8_parsed_url.path.rsplit('/', 1)[0].endswith(base):
                    return name
            return uri[1:] if uri.startswith('/') else uri
        return None

    @cached_property
    def url(self) -> Optional[str]:
        if uri := self._uri:
            if uri.startswith(('http://', 'https://')):
                return uri
            return f'{self.stream.segment_url_base}/{self.name}'
        return None

    @cached_property
    def file_name(self) -> Optional[str]:
        return self.name.rsplit('/', 1)[-1] if self.name else None

    def save(self, content: bytes):
        try:
            content = b64decode(content)
        except (ValueError, TypeError):
            pass
        return super().save(content)


class MediaSegment(FileSegment):
    def __str__(self):
        info = '\n'.join(f'#{key}:{value}' for key, value in self.info.items())
        return f'{info}\n{self.file_name}\n' if info else f'{self.file_name}\n'

    @cached_property
    def name(self):
        line = self._line
        if line.startswith(('http://', 'https://')):
            return urlparse(line).path.rsplit('/', 1)[-1]
        elif '/' in line:
            base, name = line.rsplit('/', 1)
            if base and self.stream.m3u8_parsed_url.path.rsplit('/', 1)[0].endswith(base):
                return name
        return self._line

    @cached_property
    def url(self):
        if self._line.startswith(('http://', 'https://')):
            return self._line
        return f'{self.stream.segment_url_base}/{self.name}'

    @cached_property
    def range(self) -> Optional[Tuple[int, int]]:
        try:
            seg_bytes, pos = map(int, self.info['EXT-X-BYTERANGE'].split('@'))
        except KeyError:
            return None
        else:
            return pos, pos + seg_bytes - 1

    @cached_property
    def file_name(self):
        return '{}.{}-{}.ts'.format(self.name, *self.range) if self.range else self.name

    def __repr__(self):
        extra = f' @ {self.range}' if self.range else ''
        return f'<{self.__class__.__name__}[{self._n}: {self.name}{extra}]>'

    def get(self):
        headers = {'Range': 'bytes={}-{}'.format(*self.range)} if self.range else {}
        # log.log(19, f'GET -> {self.url} headers={headers}')
        return self._get(headers)
