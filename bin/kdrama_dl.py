#!/usr/bin/env python

import json
import logging
import re
import time
from concurrent import futures
from pathlib import Path
from tempfile import TemporaryDirectory

import requests
from requests import RequestException

from requests_client import RequestsClient
from ds_tools.argparsing import ArgParser
from ds_tools.http.utils import enable_http_debug_logging
from ds_tools.logging import init_logging
from ds_tools.shell import exec_local, ExternalProcessException
from ds_tools.utils.progress import progress_coroutine

log = logging.getLogger(__name__)


def parser():
    parser = ArgParser(description='Download KDrama videos')

    dl_parser = parser.add_subparser('action', 'dl', 'Download an episode of a show')
    dl_parser.add_argument('name', help='The name of the video being downloaded (without extension)')
    dl_parser.add_argument('dl_code', help='The download code')
    dl_parser.add_argument('--save_dir', '-d', default='~/Downloads/kdramas/', help='Directory to store downloads')
    dl_parser.add_argument('--resolution', '-r', default='1080p', help='Video resolution (default: %(default)s)')
    dl_parser.add_argument('--format', '-f', default='mp4', choices=('mp4', 'mkv'), help='Video format (default: %(default)s)')
    dl_parser.add_argument('--mode', '-m', choices=('ffmpeg', 'direct'), default='direct', help='Download mode (default: %(default)s)')

    parser.add_common_arg('--debug', '-D', action='store_true', help='Enable HTTP debugging')
    parser.include_common_args('verbosity', parallel=6)
    return parser


def main():
    args = parser().parse_args()
    init_logging(args.verbose, log_path=None)

    if args.debug:
        enable_http_debug_logging()

    if args.action == 'dl':
        downloader = KdramaDownloader(args.save_dir, args.resolution, args.format)
        if args.mode == 'direct':
            downloader.download_video(args.name, args.dl_code, args.parallel)
        elif args.mode == 'ffmpeg':
            downloader.download_via_ffmpeg(args.name, args.dl_code)
        else:
            raise ValueError(f'Unknown mode={args.mode}')
    else:
        raise ValueError(f'Unknown action={args.action}')


class KdramaDownloader:
    def __init__(self, save_dir, resolution='1080p', video_format='mp4'):
        self.video_format = video_format
        self.resolution = resolution
        self.save_dir = Path(save_dir).expanduser().resolve()
        if not self.save_dir.exists():
            self.save_dir.mkdir(parents=True)
        self.client = RequestsClient('goplay.anontpp.com', scheme='https', user_agent_fmt='Mozilla/5.0')

    def download_subs(self, name, dl_code):
        sub_path = self.save_dir.joinpath(f'{name}.srt')
        if sub_path.exists():
            return sub_path

        log.info(f'Saving subtitles to {sub_path}')
        sub_resp = self.client.get('/', params={'dcode': dl_code, 'downloadccsub': 1})
        with sub_path.open('wb') as f:
            f.write(sub_resp.content)

        return sub_path

    def download_via_ffmpeg(self, name, dl_code):
        sub_path = self.download_subs(name, dl_code)
        vid_url = self.client.url_for('/', params={'dcode': dl_code, 'quality': self.resolution, 'downloadmp4vid': 1})
        vid_path = self._save_via_ffmpeg(name, vid_url, sub_path.as_posix())
        log.info(f'Successfully saved {vid_path}')

    def _save_via_ffmpeg(self, name, vid_id, sub_id, log_level='fatal'):
        vid_path = self.save_dir.joinpath(f'{name}.{self.video_format}')
        print()
        cmd = [
            'ffmpeg',
            '-loglevel', log_level,     # debug, info, warning, fatal
        ]
        if vid_id.startswith('http'):
            cmd.extend([
                # '-thread_queue_size', '2147483647',     # this is the max allowed queue size
                '-thread_queue_size', '128',
                '-timeout', '10000000',
                '-reconnect', '1',
            ])

        cmd.extend([
            '-flags', '+global_header',
            '-stats',
            # '-reconnect_streamed', '1',
            '-i', vid_id,
            '-i', sub_id,
            '-c:v', 'copy',
            '-c:a', 'copy',
            '-c:s', 'mov_text',
            '-disposition:s:0', 'default',
            '-bsf:a', 'aac_adtstoasc',
            '-f', 'mp4',
            vid_path.as_posix()
        ])
        code, out, err = exec_local(*cmd, mode='raw', raise_nonzero=True)
        return vid_path

    def _get_m3u_data(self, name, dl_code, parts_dir_base):
        m3u_path = parts_dir_base.joinpath(f'{name}.m3u8')
        # if m3u_path.exists():
        #     with m3u_path.open('r', encoding='utf-8') as f:
        #         return f.read().splitlines()
        # else:
        m3u_resp = self.client.get('/', params={'dcode': dl_code, 'quality': self.resolution, 'downloadmp4vid': 1})
        m3u_data = m3u_resp.text
        log.log(19, f'Saving video m3u to {m3u_path}')
        with m3u_path.open('w', encoding='utf-8') as f:
            f.write(m3u_data)

        return m3u_path, m3u_resp, m3u_data.splitlines()

    @staticmethod
    def _get_enc_key(m3u_data, vid_dir):
        """
        Not actually necessary - by storing the ts files with the same relative paths as the relative URI paths from
        which they were retrieved, and passing the m3u file to ffmpeg, ffmpeg will retrieve this automatically if it is
        necessary.

        :param list m3u_data: List of lines from the m3u file
        :param Path vid_dir: Path to store the key
        :return tuple: key, iv
        """
        key_path = vid_dir.joinpath('key.json')
        pat = re.compile(r'URI="(.*?)",IV=(.*)')
        url, iv = None, None
        for line in m3u_data:
            if line.startswith('#EXT-X-KEY:METHOD=AES-128,URI=') and ',IV=' in line:
                m = pat.search(line)
                if m:
                    url, iv = m.groups()
                    break
        if url is None or iv is None:
            raise ValueError(f'Unable to determine encryption key URL')

        log.debug(f'Requesting key from {url}')
        resp = requests.get(url)
        key = resp.content.hex()

        log.info(f'Saving key data to {key_path}')
        with key_path.open('w') as f:
            json.dump({'key': key, 'iv': iv}, f)

        return key, iv

    def download_video(self, name, dl_code, threads=2):
        """
        :param str name: The name of the file to save, with no extension
        :param str dl_code: The base64-encoded DL code
        :param int threads: The number of download threads to use
        """
        sub_path = self.download_subs(name, dl_code)

        with TemporaryDirectory() as tmp_dir:
            parts_dir_base = Path(tmp_dir)
            m3u_path, m3u_resp, m3u_data = self._get_m3u_data(name, dl_code, parts_dir_base)
            # key, iv = self._get_enc_key(m3u_data, vid_dir)

            part_uris_paths = [(line, parts_dir_base.joinpath(line)) for line in m3u_data if not line.startswith('#')]
            part_path_parents = {p.parent for uri, p in part_uris_paths}
            for part_dir in part_path_parents:
                if not part_dir.exists():
                    part_dir.mkdir(parents=True)

            parts_client = RequestsClient(m3u_resp.url.rsplit('/', 1)[0], user_agent_fmt='Mozilla/5.0')
            part_count = len(part_uris_paths)
            progress = progress_coroutine(part_count, name, 'parts', 0.3)
            log.info(f'Retrieving {part_count:,d} parts')

            if threads == 1:
                self._download_single_threaded(progress, part_uris_paths, parts_client)
            else:
                self._download_multi_threaded(progress, part_uris_paths, parts_client, threads)

            try:
                vid_path = self._save_via_ffmpeg(name, m3u_path.as_posix(), sub_path.as_posix())
            except ExternalProcessException as e:
                # TODO: Maybe copy the parts into a non-temp dir so the progress is not lost
                log.error(f'Error processing via ffmpeg: {e}')
                log.info('Retrying with higher ffmpeg logging verbosity...')
                vid_path = self._save_via_ffmpeg(name, m3u_path.as_posix(), sub_path.as_posix(), 'info')

        log.info(f'Successfully saved {vid_path}')

    @staticmethod
    def _download_multi_threaded(progress, part_uris_paths, parts_client, threads):
        part_count = len(part_uris_paths)

        def _process_uri(part_uri):
            try:
                return parts_client.get(part_uri)
            except RequestException as e:
                log.error(f'Error retrieving part {i}/{part_count}: {e}')
                time.sleep(1)
                log.info(f'Retrying part={i}...')
                try:
                    return parts_client.get(part_uri)
                except RequestException as e:
                    log.critical(f'Unable to retrieve part {i}')
                    raise

        with futures.ThreadPoolExecutor(max_workers=threads) as executor:
            _futures = {executor.submit(_process_uri, uri): part_path for uri, part_path in part_uris_paths}
            for i, future in enumerate(futures.as_completed(_futures)):
                resp = future.result()
                content = resp.content
                progress.send((i, len(content)))
                part_path = _futures[future]
                log.debug(f'Writing {part_path}')
                with part_path.open('wb') as f:
                    f.write(content)

    @staticmethod
    def _download_single_threaded(progress, part_uris_paths, parts_client):
        part_count = len(part_uris_paths)
        for i, (part_uri, part_path) in enumerate(part_uris_paths):
            try:
                resp = parts_client.get(part_uri)
            except RequestException as e:
                log.error(f'Error retrieving part {i}/{part_count}: {e}')
                time.sleep(1)
                log.info(f'Retrying part={i}...')
                try:
                    resp = parts_client.get(part_uri)
                except RequestException as e:
                    log.critical(f'Unable to retrieve part {i}')
                    raise

            content = resp.content
            progress.send((i, len(content)))
            log.debug(f'Writing {part_path}')
            with part_path.open('wb') as f:
                f.write(resp.content)


if __name__ == '__main__':
    main()
