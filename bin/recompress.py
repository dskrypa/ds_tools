#!/usr/bin/env python

from __future__ import annotations

import logging
import struct
from gzip import GzipFile
from io import SEEK_END
from pathlib import Path

from cli_command_parser import Command, UsageError, Positional, Option, Counter, Flag, main
from cli_command_parser.inputs import Path as IPath, NumRange, Bytes
from send2trash import send2trash, TrashPermissionError
from tqdm import tqdm
from zstandard import ZstdCompressor

from ds_tools.fs.paths import path_repr

log = logging.getLogger(__name__)


class RecompressCLI(Command, option_name_mode='*-'):
    """Recompress tar.gz files to tar.zst"""

    in_files: list[Path] = Positional(
        nargs='+', type=IPath(type='file', exists=True), help='The .tar.gz / .tgz file(s) to recompress'
    )
    out_file = Option(
        '-o', type=IPath(type='file', exists=False), help='The destination path (default: based on in_file)'
    )
    level: int = Option('-L', type=NumRange(int, min=1, max=22, include_max=True), default=12, help='Compression level')
    threads: int = Option(
        '-t', type=NumRange(int, min=-1), default=8,
        help='Threads to use for compression.  0 disables multi-threading; -1 uses all logical CPUs.'
    )
    buffer_size = Option(type=Bytes(2), default='32MiB', help='Buffer size to use when reading/writing')
    no_trash = Flag('-T', help='Do NOT send original files to the trash after recompressing them')
    verbose = Counter('-v', help='Increase logging verbosity (can specify multiple times)')

    def _init_command_(self):
        from ds_tools.logging import init_logging

        init_logging(self.verbose, log_path=None)

    def main(self):
        if self.out_file and len(self.in_files) != 1:
            raise UsageError('--out-file is not supported when multiple input files are provided')

        for in_path in self.in_files:
            try:
                self.recompress(in_path)
            except FileExistsError as e:
                log.warning(e)

    def _get_dst_path(self, src_path: Path) -> Path:
        if self.out_file:
            return self.out_file

        path = src_path.resolve()
        dst_path = path.parent.joinpath(f'{path.stem}.tar.zst' if path.suffix == '.tgz' else f'{path.stem}.zst')
        if not dst_path.exists():
            return dst_path

        raise FileExistsError(
            f'Unable to recompress {path_repr(src_path)} because {path_repr(dst_path)} already exists'
        )

    def recompress(self, src_path: Path):
        dst_path = self._get_dst_path(src_path)
        dst_path.parent.mkdir(parents=True, exist_ok=True)

        buf_size = self.buffer_size
        log.info(f'Recompressing to {path_repr(dst_path)} with level={self.level}, threads={self.threads}, {buf_size=}')

        cctx = ZstdCompressor(level=self.level, threads=self.threads)
        with GzipFile(src_path, 'rb') as src_file:
            if src_path.stat().st_size < 2147483648:  # 2 GB
                size = _get_size(src_path)  # Only works when uncompressed < 4GB
            else:
                size = src_file.seek(0, SEEK_END)  # This is much slower
                src_file.seek(0)

            with tqdm(total=size, unit='B', unit_scale=True, smoothing=0.1, maxinterval=1) as prog_bar:
                with open(dst_path, 'wb') as dst_f, cctx.stream_writer(dst_f) as dst_file:
                    read, write = src_file.read, dst_file.write
                    while buf := read(buf_size):
                        write(buf)
                        prog_bar.update(len(buf))

        if not self.no_trash:
            log.info(f'Sending {path_repr(src_path)} to trash')
            try:
                send2trash(src_path)
            except TrashPermissionError as e:
                log.warning(f'Error sending {path_repr(src_path)} to trash: {e}')


def _get_size(path: Path) -> int:
    # This only works for uncompressed sizes < 4 GB
    with open(path, 'rb') as f:
        f.seek(-4, SEEK_END)
        return struct.unpack('<I', f.read(4))[0]


if __name__ == '__main__':
    main()
