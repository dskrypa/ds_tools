#!/usr/bin/env python

import logging
import time
from collections import defaultdict
from concurrent import futures
from functools import cached_property
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Dict, Optional, Tuple, List
from urllib.parse import urlparse, ParseResult

from requests import Session, RequestException

from ds_tools.argparsing import ArgParser
from ds_tools.http.utils import enable_http_debug_logging
from ds_tools.input import choose_item
from ds_tools.logging import init_logging
from ds_tools.shell import exec_local, ExternalProcessException
from ds_tools.utils.progress import progress_coroutine
from requests_client.client import RequestsClient

log = logging.getLogger(__name__)


def parser():
    parser = ArgParser(description='Download and merge split videos in a M3U8 playlist')

    parser.add_argument('source', help='URL that provides stream info or path to a .m3u8 file')
    parser.add_argument('--goplay', '-g', action='store_true', help='The info url is a goplay.anontpp.com dl code')
    parser.add_argument('--name', '-n', help='The name of the video being downloaded (without extension)', required=True)
    parser.add_argument('--save_dir', '-d', default='~/Downloads/m3u8/', help='Directory to store downloads')
    parser.add_argument('--format', '-f', default='mp4', choices=('mp4', 'mkv'), help='Video format (default: %(default)s)')
    parser.add_argument('--local', '-l', action='store_true', help='Specify if the target ts part files already exist')

    parser.add_common_arg('--debug', '-D', action='store_true', help='Enable HTTP debugging')
    parser.include_common_args('verbosity', parallel=4)
    return parser


def main():
    args = parser().parse_args()
    init_logging(args.verbose, log_path=None)

    if args.debug:
        enable_http_debug_logging()

    # TODO: Handle subtitles

    video = VideoStream(args.source, args.save_dir, args.name, args.format, args.goplay, args.local)
    if args.local:
        video.save_via_ffmpeg()
    else:
        video.download(args.parallel)


class VideoStream:
    def __init__(self, source: str, save_dir: str, name: str, ext: str, goplay: bool = False, local: bool = False):
        self.name = name
        self.ext = ext
        self.local = local
        self.goplay = goplay
        self._temp_dir = None
        self.save_dir = Path(save_dir).expanduser().resolve()
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
        elif self.goplay:
            client = RequestsClient('goplay.anontpp.com', scheme='https', user_agent_fmt='Mozilla/5.0')
            return client.url_for('/', params={'dcode': self.info_url, 'quality': '1080p', 'downloadmp4vid': 1})

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
            for i, future in enumerate(futures.as_completed(_futures)):
                resp = future.result()
                content = resp.content
                progress.send((i, len(content)))
                segment = _futures[future]  # type: MediaSegment
                segment.save(content)

        self.ext_m3u.save_revised()
        self.save_via_ffmpeg()

    def save_via_ffmpeg(self):
        try:
            vid_path = self._save_via_ffmpeg()
        except ExternalProcessException as e:
            # TODO: Maybe copy the parts into a non-temp dir so the progress is not lost
            log.error(f'Error processing via ffmpeg: {e}')
            log.info('Retrying with higher ffmpeg logging verbosity...')
            vid_path = self._save_via_ffmpeg('info')

        log.info(f'Successfully saved {vid_path}')

    def _save_via_ffmpeg(self, log_level='fatal'):
        vid_path = self.save_dir.joinpath(f'{self.name}.{self.ext}')
        print()
        cmd = [
            'ffmpeg',
            '-loglevel', log_level,     # debug, info, warning, fatal
        ]

        cmd.extend([
            '-flags', '+global_header',
            '-stats',
            '-protocol_whitelist', 'file,http,https,tcp,tls,crypto',
            '-allowed_extensions', 'ALL',
            # '-reconnect_streamed', '1',
            '-i', self.ext_m3u.revised_path.as_posix(),
            # '-i', sub_id,
            '-c:v', 'copy',
            '-c:a', 'copy',
            # '-c:s', 'mov_text',
            '-disposition:s:0', 'default',
            '-bsf:a', 'aac_adtstoasc',
            '-f', self.ext,
            vid_path.as_posix()
        ])
        code, out, err = exec_local(*cmd, mode='raw', raise_nonzero=True)
        return vid_path


class EXTM3U:
    def __init__(self, stream: 'VideoStream', content: str, collapse: bool = True):
        self.stream = stream
        self.content = content
        # self._headers = []
        # self._footers = []
        self.collapse = collapse

    @cached_property
    def _all_segments(self) -> List['M3USegment']:
        segments = []
        segment = {}
        for n, line in enumerate(filter(None, map(str.strip, self.content.splitlines()))):
            if line.startswith('#'):
                try:
                    key, value = line[1:].split(':', 1)
                except Exception as e:
                    segments.append(M3USegment(self, n, line))
                    # if segments:
                    #     self._footers.append(line)
                    # else:
                    #     self._headers.append(line)
                else:
                    if key == 'EXTINF' or segment:
                        segment[key] = value
                    else:
                        segments.append(M3USegment(self, n, line))
                        # self._headers.append(line)
            else:
                segments.append(MediaSegment(self, n, line, segment))
                segment = {}
        return segments

    @cached_property
    def _segments(self) -> List['MediaSegment']:
        # segments = []
        # segment = {}
        # for n, line in enumerate(filter(None, map(str.strip, self.content.splitlines()))):
        #     if line.startswith('#'):
        #         try:
        #             key, value = line[1:].split(':', 1)
        #         except Exception as e:
        #             self._all_segments.append(M3USegment(self, n, line))
        #             # if segments:
        #             #     self._footers.append(line)
        #             # else:
        #             #     self._headers.append(line)
        #         else:
        #             if key == 'EXTINF' or segment:
        #                 segment[key] = value
        #             else:
        #                 self._all_segments.append(M3USegment(self, n, line))
        #                 # self._headers.append(line)
        #     else:
        #         seg = MediaSegment(self, n, line, segment)
        #         self._all_segments.append(seg)
        #         segments.append(seg)
        #         segment = {}
        # return segments
        return [s for s in self._all_segments if isinstance(s, MediaSegment)]

    @cached_property
    def collapsed(self) -> 'EXTM3U':
        sio = StringIO()
        sizes = defaultdict(int)
        written = set()
        for segment in self._segments:
            sizes[segment.name] = max(sizes[segment.name], segment.range[1])

        for segment in self._all_segments:
            if isinstance(segment, MediaSegment):
                if (name := segment.name) not in written:
                    written.add(name)
                    info = segment.info.copy()
                    info['EXT-X-BYTERANGE'] = '{}@0'.format(sizes[name] + 1)
                    sio.write(str(MediaSegment(self, segment._n, name, info)))
            else:
                sio.write(str(segment))

        return self.__class__(self.stream, sio.getvalue(), False)

    @cached_property
    def segments(self) -> List['MediaSegment']:
        if self.collapse and any(seg.range for seg in self._segments):
            return self.collapsed._segments
            # segments = {}
            # sizes = defaultdict(int)
            # for segment in self._segments:
            #     sizes[segment.name] = max(sizes[segment.name], segment.range[1])
            #     segments[segment.name] = segment.info.copy()
            #
            # collapsed = []
            # for name, info in sorted(segments.items()):
            #     info['EXT-X-BYTERANGE'] = '{}@0'.format(sizes[name] + 1)
            #     collapsed.append(MediaSegment(self, n, name, info))
            # return collapsed
        else:
            return self._segments

    @cached_property
    def revised_path(self) -> Path:
        return self.stream.temp_dir_path.joinpath(f'{self.stream.name}.revised.m3u8')

    def save_revised(self):
        with self.revised_path.open('w', encoding='utf-8') as f:
            f.write('\n'.join(map(str, self._all_segments)))
            f.write('\n')
            # f.write('\n'.join(self._headers) + '\n')
            # for segment in self.segments:
            #     for key, value in segment.info.items():
            #         f.write(f'#{key}:{value}\n')
            #     f.write(f'{segment.file_name}\n')
            # f.write('\n'.join(self._footers) + '\n')


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

    @property
    def stream(self):
        return self.ext_m3u.stream

    def __lt__(self, other: 'M3USegment') -> bool:
        return self._n < other._n

    def __eq__(self, other: 'M3USegment') -> bool:
        return self.ext_m3u == other.ext_m3u and self._n == other._n


class KeySegment(M3USegment):
    """
    #EXT-X-KEY:METHOD=AES-128,URI="/20201223/UKvWlT0p/1000kb/hls/key.key"
        -> would need the first part of the url, or to dl the key & replace URI value with path to key
    #EXT-X-KEY:METHOD=NONE

    pat = re.compile(r'URI="(.*?)",IV=(.*)')
        -> may contain additional parts after the URI
    """


class MediaSegment(M3USegment):
    def __str__(self):
        info = '\n'.join(f'#{key}:{value}' for key, value in self.info.items())
        return f'{info}\n{self.file_name}\n' if info else f'{self.file_name}\n'

    @property
    def name(self):
        line = self._line
        if line.startswith(('http://', 'https://')):
            return urlparse(line).path.rsplit('/', 1)[-1]
        elif '/' in line:
            base, name = line.rsplit('/', 1)
            if base and self.stream.m3u8_parsed_url.path.rsplit('/', 1)[0].endswith(base):
                return name
        return self._line

    @property
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

    @cached_property
    def path(self):
        return self.stream.temp_dir_path.joinpath(self.file_name)

    def __repr__(self):
        return f'<M3USegment[{self.name} @ {self.range}]>' if self.range else f'<M3USegment[{self.name}]>'

    def get(self):
        headers = {'Range': 'bytes={}-{}'.format(*self.range)} if self.range else {}
        # log.log(19, f'GET -> {self.url} headers={headers}')

        for t in Retries():
            try:
                resp = self.stream.session.get(self.url, headers=headers)
                resp.raise_for_status()
            except RequestException as e:
                exc = e
                log.error(f'Error retrieving {self!r}, will sleep {t}s: {e}')
                time.sleep(t)
                log.info(f'Retrying {self!r}...')
            else:
                return resp

        log.critical(f'Unable to retrieve {self!r}')
        raise exc

    def save(self, content):
        log.debug(f'Writing {self.file_name}')
        if not self.path.parent.exists():
            self.path.parent.mkdir(parents=True)
        with self.path.open('wb') as f:
            f.write(content)


class Retries:
    def __init__(self, min: int = 5, max: int = 20, incr: int = 5, per_step: int = 3):
        self.delay = min
        self.max = max
        self.incr = incr
        self.per_step = per_step
        self.step_retries = 0

    def __iter__(self):
        return self

    def __next__(self):
        if self.step_retries >= self.per_step:
            if self.delay < self.max:
                self.step_retries = 0
                self.delay = min(self.delay + self.incr, self.max)
        else:
            self.step_retries += 1
        return self.delay


if __name__ == '__main__':
    main()
