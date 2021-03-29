import logging
from concurrent import futures
from functools import cached_property
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
from typing import TYPE_CHECKING, Optional
from urllib.parse import urlparse, ParseResult

from requests import Session

from ds_tools.input import choose_item
from ds_tools.shell import ExternalProcessException
from ds_tools.utils.progress import progress_coroutine
from requests_client.client import RequestsClient
from .m3u import EXTM3U
from .utils import Ffmpeg

if TYPE_CHECKING:
    from .segments import MediaSegment

__all__ = ['VideoStream', 'GoplayVideoStream']
log = logging.getLogger(__name__)


class VideoStream:
    def __init__(self, source: str, save_dir: str, name: str, ext: str, local: bool = False, ffmpeg_dl: bool = False):
        self.name = name
        self.ext = ext
        self.local = local
        self._temp_dir = None
        self.save_dir = Path(save_dir).expanduser().resolve()
        self.ffmpeg_dl = ffmpeg_dl
        if not self.save_dir.exists():
            self.save_dir.mkdir(parents=True)

        src_path = Path(source).expanduser().resolve()
        try:
            exists = src_path.exists()
        except OSError:
            exists = False

        if exists:
            log.debug(f'Source exists: {source}')
            if src_path.suffix != '.m3u8':
                raise ValueError(f'Unexpected source type: {src_path}')
            self.info_url = None
            self.m3u8_path = src_path
        elif local:
            raise ValueError(f'Invalid {source=!r} for --local mode')
        else:
            self.info_url = source
            self.m3u8_path = self.temp_dir_path.joinpath(f'{self.name}.m3u8')

        self.session = Session()
        self._exiting = Event()
        self._m3u8_data = None

    @cached_property
    def temp_dir_path(self) -> Path:
        if self.info_url is None and self.local:
            log.debug(f'Using existing temp_dir_path={self.m3u8_path.parent}')
            return self.m3u8_path.parent
        self._temp_dir = TemporaryDirectory(prefix=self.save_dir.as_posix() + '/')
        log.debug(f'Made new temp_dir={self._temp_dir.name}')
        self._temp_dir._finalizer.detach()  # noqa
        return Path(self._temp_dir.name)

    @cached_property
    def m3u8_url(self) -> Optional[str]:
        if not self.info_url:
            return None

        resp = self.session.get(self.info_url)
        log.debug(f'M3U8 Data:\n{resp.text}')

        streams = {}
        info, res = None, None
        for line in resp.text.splitlines():
            if line.startswith('#EXT-X-STREAM-INF:'):
                info = line.split(':', 1)[1]
                # attrs = {
                #     m.group(1): m.group(2) or m.group(3) for m in re.finditer(r'([^=]+)=(?:"([^"]+)"|([^,]+)),?', info)
                # }
                # res = attrs['RESOLUTION']
            elif line.endswith('.m3u8') and not line.startswith('#') and info:
                if line.startswith(('http://', 'https://')):
                    streams[info] = line
                else:
                    prefix = resp.url.rsplit('/', 1)[0]
                    streams[info] = f'{prefix}/{line}'

                info, res = None, None

        if not streams:
            if urlparse(self.info_url).path.lower().endswith('.m3u8'):
                self._m3u8_data = resp.text
                return self.info_url
            raise RuntimeError(f'Unable to find stream info in response from {self.info_url}:\n{resp.text}')

        stream = choose_item(streams, 'stream')
        return streams[stream]

    @cached_property
    def m3u8_parsed_url(self) -> Optional[ParseResult]:
        return urlparse(self.m3u8_url) if self.m3u8_url else None

    @cached_property
    def segment_url_base(self) -> Optional[str]:
        return self.m3u8_url.rsplit('/', 1)[0] if self.m3u8_url else None

    @cached_property
    def segment_url_bare_base(self) -> Optional[str]:
        return f'{self.m3u8_parsed_url.scheme}://{self.m3u8_parsed_url.netloc}' if self.m3u8_url else None

    @cached_property
    def ext_m3u(self) -> 'EXTM3U':
        if self.m3u8_url:
            if self._m3u8_data is None:
                resp = self.session.get(self.m3u8_url)
                self._m3u8_data = resp.text

            with self.m3u8_path.open('w', encoding='utf-8') as f:
                log.debug(f'm3u8 content:\n{self._m3u8_data}')
                f.write(self._m3u8_data)
            return EXTM3U(self, self._m3u8_data)
        else:
            with self.m3u8_path.open('r', encoding='utf-8') as f:
                return EXTM3U(self, f.read())

    def download(self, threads=2):
        """
        :param int threads: The number of download threads to use
        """
        part_count = len(self.ext_m3u.segments)
        progress = progress_coroutine(part_count, self.name, 'segments', 0.3)
        log.info(f'Retrieving {part_count:,d} segments')

        with futures.ThreadPoolExecutor(max_workers=threads) as executor:
            _futures = {executor.submit(seg.get): seg for seg in self.ext_m3u.segments}
            try:
                for i, future in enumerate(futures.as_completed(_futures)):
                    resp = future.result()
                    content = resp.content
                    progress.send((i, len(content)))
                    segment = _futures[future]  # type: MediaSegment
                    segment.save(content)
            except BaseException:
                self._exiting.set()
                raise

        self.ext_m3u.save_revised()
        self.save_via_ffmpeg()

    @property
    def _video_input(self):
        if self.ffmpeg_dl:
            return self.m3u8_url

        revised_path = self.ext_m3u.revised_path
        if self.local and not revised_path.exists():
            self.ext_m3u.save_revised()
        return revised_path

    @cached_property
    def _ffmpeg(self) -> 'Ffmpeg':
        return Ffmpeg(self._video_input, fmt=self.ext)

    def save_via_ffmpeg(self):
        vid_path = self.save_dir.joinpath(f'{self.name}.{self.ext}')
        try:
            vid_path = self._ffmpeg.save(vid_path.as_posix())
        except ExternalProcessException as e:
            log.error(f'Error processing via ffmpeg: {e}')
            log.info('Retrying with higher ffmpeg logging verbosity...')
            vid_path = self._ffmpeg.save(vid_path.as_posix(), log_level='info')

        log.info(f'Successfully saved {vid_path}')


class GoplayVideoStream(VideoStream):
    @cached_property
    def client(self):
        return RequestsClient('goplay.anontpp.com', scheme='https', user_agent_fmt='Mozilla/5.0')

    @cached_property
    def m3u8_url(self) -> Optional[str]:
        return self.client.url_for('/', params={'dcode': self.info_url, 'quality': '1080p', 'downloadmp4vid': 1})

    @cached_property
    def sub_path(self) -> Path:
        return self.save_dir.joinpath(f'{self.name}.srt')

    def download_subtitles(self):
        if self.sub_path.exists():
            return self.sub_path

        log.info(f'Saving subtitles to {self.sub_path}')
        sub_resp = self.client.get('/', params={'dcode': self.info_url, 'downloadccsub': 1})
        with self.sub_path.open('wb') as f:
            f.write(sub_resp.content)

        return self.sub_path

    @cached_property
    def _ffmpeg(self) -> 'Ffmpeg':
        self.download_subtitles()
        return Ffmpeg(self._video_input, self.sub_path, fmt=self.ext, subs='mov_text')
