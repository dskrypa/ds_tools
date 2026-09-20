#!/usr/bin/env python

from __future__ import annotations

import logging
from contextlib import ExitStack
from tarfile import TarFile
from typing import TYPE_CHECKING, Iterable

from cli_command_parser import Command, Option, Flag, Counter, main
from cli_command_parser.inputs import Path as IPath, NumRange
from tqdm import tqdm
from zstandard import ZstdCompressor

from ds_tools.fs.paths import path_repr
from ds_tools.output.formatting import readable_bytes

if TYPE_CHECKING:
    from pathlib import Path
    from tarfile import TarInfo

log = logging.getLogger(__name__)


class CompressCLI(Command, option_name_mode='*-'):
    """
    Create a tar archive using zstandard compression.

    The primary purpose of this script is to be able to create a tar.zst file while showing a progress bar.  While the
    zstd CLI supports showing progress, it still requires tar to support multiple input files.  While the tar CLI
    supports calling the zstd CLI with additional parameters, the zstd CLI doesn't support displaying progress when
    running that way.

    Example tar/zstd CLI invocations that are alternatives to using this script::

        $ tar -I 'zstd -T12 -9' -cf foo.tar.zst foo  # level=9, cpus=12, no progress indicator

        $ tar -cf - foo | zstd -T8 -15 -o foo.tar.zst  # level=15, cpus=8, shows progress indicator
    """

    inputs = Option(
        '-i', nargs='+', type=IPath(type='file|dir', exists=True), required=True, help='Files to include in the archive'
    )
    recursive = Flag('-r', help='Whether directories should be processed recursively')
    output = Option('-o', type=IPath(type='file', exists=False), required=True, help='Output archive path')
    level = Option('-L', type=NumRange(int, min=1, max=23), default=3, help='Compression level')
    no_progress = Flag('-P', help='Skip the progress indicator')

    verbose = Counter('-v', help='Increase logging verbosity (can specify multiple times)')

    def _init_command_(self):
        from ds_tools.logging import init_logging

        init_logging(self.verbose)

    def main(self):
        self.output.parent.mkdir(parents=True, exist_ok=True)
        if self.no_progress:
            self._create_archive_simple()
        else:
            self._create_archive_with_progress()

    def _create_archive_simple(self):
        recursive = self.recursive
        with (
            self.output.open('wb') as f,
            ZstdCompressor(self.level).stream_writer(f) as zf,
            TarFile(self.output.name, 'w', zf) as tf,
        ):
            log.info(f'Creating {path_repr(self.output)}')
            for path in self.inputs:
                log.log(19, f'Adding {path.name} to archive...')
                tf.add(path, path.name, recursive=recursive)

    def _create_archive_with_progress(self):
        with ZstdArchiveBuilder(self.output, self.level, self.recursive) as builder:
            builder.compress(self.inputs)


class ZstdArchiveBuilder:
    _tar_file: TarFile | None = None
    _tar_info: list[tuple[Path, TarInfo]]

    def __init__(self, path: Path, level: int = 3, recursive: bool = True):
        self.path = path
        self.level = level
        self.recursive = recursive
        self._stack = ExitStack()
        self._tar_info = []

    def compress(self, paths: list[Path]):
        """
        Create a zstd-compressed archive containing the specified paths.

        All target paths are processed before any files are read - it is assumed that none of the files change between
        the discovery and read/compression steps.

        :param paths: The paths to include in the archive.
        """
        assert self._tar_file is not None  # Expect the instance to be used as a context manager

        self._add_paths(paths)
        total_size = sum(ti.size for _, ti in self._tar_info if ti.isreg())
        log.info(f'Creating {path_repr(self.path)}')
        log.info(f'Original size: {readable_bytes(total_size)}')

        add_file = self._tar_file.addfile
        with tqdm(total=total_size, unit='B', unit_scale=True, smoothing=0.1, maxinterval=1) as prog_bar:
            for path, tar_info in self._tar_info:
                log.log(19, f'Adding {tar_info.name} to archive...')
                if tar_info.isreg():
                    with open(path, 'rb') as f:
                        add_file(tar_info, f)
                    prog_bar.update(tar_info.size)
                else:
                    add_file(tar_info)

        if final_size := self.path.stat().st_size:
            log.info(f'Compressed size: {readable_bytes(final_size)} ({final_size / total_size:.2%})')

    def _add_paths(self, paths: Iterable[Path], parent: str | None = None):
        assert self._tar_file is not None
        if self.recursive:
            for path in paths:
                arc_name = f'{parent}/{path.name}' if parent else path.name
                tar_info = self._tar_file.gettarinfo(path, arc_name)
                self._tar_info.append((path, tar_info))
                if tar_info.isdir():
                    self._add_paths(path.iterdir(), arc_name)
        else:
            self._tar_info.extend((path, self._tar_file.gettarinfo(path, path.name)) for path in paths)

    def __enter__(self) -> ZstdArchiveBuilder:
        f = self._stack.enter_context(self.path.open('wb'))
        zstd_writer = self._stack.enter_context(ZstdCompressor(self.level).stream_writer(f))
        self._tar_file = self._stack.enter_context(TarFile(self.path.name, 'w', zstd_writer))
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        result = self._stack.__exit__(exc_type, exc_val, exc_tb)
        self._tar_file = None
        return result


if __name__ == '__main__':
    main()
