#!/usr/bin/env python

from __future__ import annotations

from pathlib import Path

from cli_command_parser import Command, SubCommand, ParamGroup, Positional, Option, Flag, Counter, main
from cli_command_parser.inputs import Path as IPath

import logging
import re
from subprocess import check_call, check_output
from tempfile import TemporaryDirectory
from typing import Any, Iterable, Optional, Union, Collection

from ds_tools.__version__ import __author_email__, __version__  # noqa
from ds_tools.caching.decorators import cached_property
from ds_tools.output.formatting import readable_bytes
from ds_tools.output.printer import Printer

log = logging.getLogger(__name__)
STEAMAPPS_DIR = Path('C:/Program Files (x86)/Steam/steamapps')
NMS_PATH = STEAMAPPS_DIR.joinpath('common', "No Man's Sky")
PAK_PATH = NMS_PATH.joinpath('GAMEDATA', 'PCBANKS')
EXCLUDE = ('AUDIO', 'FONTS', 'MODELS', 'MUSIC', 'SHADERS', 'TEXTURES', 'SCENES')


class NMSExtractor(Command, description='NMS Extractor'):
    action = SubCommand()
    verbose = Counter('-v', help='Increase logging verbosity (can specify multiple times)')

    with ParamGroup(description='NMS Install Location Options'):
        steamapps_dir = Option(default=STEAMAPPS_DIR, type=Path, help='The path to the steamapps directory, containing appmanifest_*.acf files')
        nms_dir = Option(type=Path, help="The directory in which No Man's Sky is installed (default: $steamapps_dir/common/No Man's Sky)")

    with ParamGroup(description='PSARC Options'):
        psarc = Option('-p', default='~/sbin/psarc.exe', type=IPath(type='file', exists=True), help='Path to the psarc binary to use')
        mbin_compiler = Option('-m', default='~/sbin/MBINCompiler.exe', metavar='PATH', help='Path to the MBINCompiler binary to use')
        debug = Flag('-d', help='Show more psarc output')

    with ParamGroup(description='Output Options'):
        output = Option('-o', default='~/etc/no_mans_sky/extracted/', metavar='PATH', help='Output directory')

    def _init_command_(self):
        from ds_tools.logging import init_logging

        init_logging(self.verbose, log_path=None)
        PakFile._psarc_loc = self.psarc.as_posix()

    @cached_property
    def nms(self) -> NoMansSky:
        return NoMansSky(self.psarc, Path(self.output).expanduser(), self.steamapps_dir, self.nms_dir)

    @cached_property
    def mbc(self) -> MbinCompiler:
        return MbinCompiler(Path(self.mbin_compiler), Path(self.output))


class Find(NMSExtractor, help='Find the PAK file(s) containing the specified MBIN/EXML file(s)'):
    files = Positional(nargs='+', help='The name of one or more MBIN/EXML files, with or without extension')

    def main(self):
        from collections import defaultdict

        to_find = {
            name if name.endswith('.MBIN') else f'{name[:-5]}.MBIN' if name.endswith('.EXML') else f'{name}.MBIN'
            for name in map(str.upper, self.files)
        }
        results = defaultdict(list)
        for pak in self.nms.pak_files(debug=self.debug):
            for name in list(to_find):
                if mbin_path := pak.get_content_path(name):
                    results[pak.name].append(mbin_path)
                    to_find.remove(name)
                    break
            if not to_find:
                break

        if to_find:
            results['__NOT_FOUND__'] = sorted(to_find)

        Printer('yaml').pprint(results)


class FindAll(NMSExtractor, help='Find the PAK files(s) containing any files with paths containing the given text'):
    name = Positional(help='The (partial) name of a file to find')

    def main(self):
        to_find = self.name
        results = {}
        for pak in self.nms.pak_files(debug=self.debug):
            if pak_results := list(pak.find_paths_containing(to_find)):
                results[pak.name] = pak_results

        if results:
            Printer('yaml').pprint(results)
        else:
            log.warning('No results.')


class Extract(NMSExtractor, help='Extract MBIN files from PAK files'):
    all = Flag('-A', help=f'Extract all files (default: skip {EXCLUDE})')

    def main(self):
        if self.all:
            self.nms.extract_all_pak_files(self.debug)
        else:
            self.nms.extract_filtered_pak_files(EXCLUDE, self.debug)


class MbinCompiler:
    def __init__(self, path: Path, out_dir: Path = None):
        self._path = path.expanduser().resolve().as_posix()
        if out_dir:
            out_dir = out_dir.expanduser().resolve()
            if not out_dir.exists():
                out_dir.mkdir(parents=True)
            self._out_dir = out_dir.as_posix()
        else:
            self._out_dir = None

    def convert(self, path: Union[Path, str]):
        """
        Convert the given mbin->exml / exml->mbin.  If out_dir was not specified, then the output will be written to the
        same directory that the specified file is in now.

        :param path: The path to the file to convert
        """
        path = (Path(path) if isinstance(path, str) else path).expanduser().resolve()
        extra = ('-d', self._out_dir) if self._out_dir else ()
        check_call([self._path, 'convert', '-q', *extra, path.as_posix()])

    def convert_many(self, paths: Collection[str]):
        if self._out_dir:
            raise ConfigError('Unable to convert with a specific output dir when converting multiple files')
        check_call([self._path, 'convert', '-q', *paths])


class NoMansSky:
    def __init__(self, psarc_path: Path, output_dir: Path, steamapps_dir: Path, install_dir: Path = None):
        self.psarc_path = psarc_path
        self.steamapps_dir = steamapps_dir
        self.install_dir = install_dir or steamapps_dir.joinpath('common', 'No Man\'s Sky')
        self.output_dir = output_dir.joinpath(self.build_id)
        if not self.output_dir.exists():
            self.output_dir.mkdir(parents=True)

    @cached_property
    def manifest(self) -> dict[str, Any]:
        path_275850 = self.steamapps_dir.joinpath(f'appmanifest_275850.acf')
        if path_275850.exists():
            manifest = read_acf(path_275850)
            if manifest['AppState']['name'] == 'No Man\'s Sky':
                return manifest
        # The following is present in case the app ID is not the same for everyone
        for path in self.steamapps_dir.glob('appmanifest_*.acf'):
            if path != path_275850:
                manifest = read_acf(path)
                if manifest['AppState']['name'] == 'No Man\'s Sky':
                    return manifest
        raise RuntimeError(f'Unable to find an app manifest for NMS in {self.steamapps_dir.as_posix()}')

    @cached_property
    def build_id(self) -> str:
        return self.manifest['AppState']['buildid']

    @cached_property
    def pak_dir(self) -> Path:
        return self.install_dir.joinpath('GAMEDATA', 'PCBANKS')

    def pak_files(self, exclude_packed_dirs: Iterable[str] = None, debug: bool = False) -> list['PakFile']:
        exclude_packed_dirs = set(exclude_packed_dirs) if exclude_packed_dirs else None
        return [PakFile(path, exclude_packed_dirs, debug=debug) for path in sorted(self.pak_dir.glob('*.pak'))]

    def extract_all_pak_files(self, debug: bool = False):
        log.info(f'Extracting {self.pak_dir.as_posix()} -> {self.output_dir.as_posix()}')
        pak_files = [PakFile(path, debug=debug) for path in sorted(self.pak_dir.glob('*.pak'))]
        total = len(pak_files)
        for i, pak in enumerate(pak_files, 1):
            pak.extract(self.output_dir, i, total)

    def extract_filtered_pak_files(self, exclude_packed_dirs: Iterable[str], debug: bool = False):
        pak_files = self.pak_files(exclude_packed_dirs, debug)
        to_extract = [pak for pak in pak_files if pak.top_level_filtered]
        total = len(to_extract)
        log.info(
            f'Extracting {total} / {len(pak_files)} filtered PAK files from {self.pak_dir.as_posix()} ->'
            f' {self.output_dir.as_posix()}'
        )
        for i, pak in enumerate(to_extract, 1):
            pak.extract(self.output_dir, i, total)


class PakFile:
    _psarc_loc: str = None

    def __init__(self, path: Path, exclude_packed_dirs: set[str] = None, debug: bool = False):
        self.path = path
        self.name = path.name
        self.exclude_packed_dirs = exclude_packed_dirs
        self.debug = debug

    @cached_property
    def top_level_names(self) -> set[str]:
        command = [self._psarc_loc, 'list', self.path.as_posix(), '-q']
        return {p.split(maxsplit=1)[0].split('/', 1)[0] for p in check_output(command, encoding='utf-8').splitlines()}

    @cached_property
    def content_paths(self) -> set[str]:
        command = [self._psarc_loc, 'list', self.path.as_posix(), '-q']
        exclude_packed_dirs = self.exclude_packed_dirs
        return {
            p.split(maxsplit=1)[0]
            for p in check_output(command, encoding='utf-8').splitlines()
            if not exclude_packed_dirs or p.split('/', 1)[0] not in exclude_packed_dirs
        }

    @cached_property
    def top_level_filtered(self) -> set[str]:
        exclude_packed_dirs = self.exclude_packed_dirs
        return self.top_level_names.difference(exclude_packed_dirs) if exclude_packed_dirs else self.top_level_names

    def __contains__(self, item: str) -> bool:
        return any(p.endswith(item) for p in self.content_paths)

    def find_paths_containing(self, text: str):
        lc_text = text.lower()
        for path in self.content_paths:
            if lc_text in path.lower():
                yield path

    def get_content_path(self, mbin_name: str) -> Optional[str]:
        for path in self.content_paths:
            if path.endswith(mbin_name):
                return path
        return None

    def extract(self, output_dir: Path, n: int = None, total: int = None):
        suffix = f' ({n} / {total})' if n and total else ''
        names = ','.join(sorted(self.top_level_filtered))
        log.info(f'Extracting from {self.name} [{readable_bytes(self.path.stat().st_size)}]{suffix} content={names}')
        if self.top_level_names != self.top_level_filtered:
            self._extract_filtered(output_dir)
        else:
            self._extract_all(output_dir)

    def _extract_all(self, output_dir: Path):
        command = [self._psarc_loc, 'extract', f'--input={self.path.as_posix()}', f'--to={output_dir.as_posix()}']
        if not self.debug:
            command.append('-q')
        log.debug(f'Running {command=}')
        check_call(command)

    def _extract_filtered(self, output_dir: Path):
        with TemporaryDirectory() as tmp_dir_name:
            tmp_dir = Path(tmp_dir_name)
            files = '\n'.join(f'        <file archivepath="{p}" />' for p in self.content_paths)
            psarc_xml = (
                f'<psarc>\n'
                f'    <extract archive="{self.path.as_posix()}" to="{output_dir.as_posix()}">\n'
                f'{files}'
                f'    </extract>\n'
                f'</psarc>\n'
            )
            tmp_xml = tmp_dir.joinpath('to_extract.xml')
            tmp_xml.write_text(psarc_xml)
            command = [self._psarc_loc, 'extract', f'--xml={tmp_xml.as_posix()}']
            if not self.debug:
                command.append('-q')
            log.debug(f'Running {command=}')
            check_call(command)


def read_acf(path: Path):
    section, building = None, None
    build_stack = [(None, {})]
    kv_match = re.compile(r'^"(.+?)"\s+"(.+?)"$').match
    for line in map(str.strip, path.read_text('utf-8').splitlines()):
        if line == '}':
            inner_key, inner_val = section, building
            section, building = build_stack.pop()
            building[inner_key] = inner_val
        elif m := kv_match(line):
            key, val = m.groups()
            building[key] = val
        elif line != '{':
            if section:
                build_stack.append((section, building))
            section = line[1:-1]
            building = {}

    return building


class ConfigError(Exception):
    """Error to be raised when an invalid configuration is detected"""


if __name__ == '__main__':
    main()
