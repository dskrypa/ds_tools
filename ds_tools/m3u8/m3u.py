import logging
from collections import defaultdict
from functools import cached_property
from io import StringIO
from pathlib import Path
from typing import TYPE_CHECKING, List

from .segments import M3USegment, FileSegment, KeySegment, MediaSegment

if TYPE_CHECKING:
    from .stream import VideoStream

log = logging.getLogger(__name__)


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
