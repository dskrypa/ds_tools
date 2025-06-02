#!/usr/bin/env python

from __future__ import annotations

import logging
import os
from concurrent.futures import as_completed, ThreadPoolExecutor
from functools import cached_property
from pathlib import Path
from struct import Struct
from subprocess import check_output, CalledProcessError, PIPE
from tempfile import TemporaryDirectory

from cli_command_parser import Command, Positional, Option, Counter, main
from cli_command_parser.inputs import Path as IPath
from tqdm import tqdm

from ds_tools.fs.paths import iter_sorted_files

log = logging.getLogger(__name__)

HEADER_EXT_MAP = {b'mabf': '.mab', b'sabf': '.sab', b'OggS': '.ogg'}
FILE = IPath(type='file', exists=True)
SIZE = Struct('<ll')


class UnrealAudioConverter(Command):
    """
    Unreal Audio Converter

    Converts .uasset / .uexp files containing audio data from games that use the Unreal engine into playable formats.
    The .uasset / .uexp files must have already been extracted from the game before this script can be used.

    Steps to take before this script can be used:

    Identify packages containing sound files by using UnrealPak from https://www.unrealengine.com/en-US/linux

    Example::

        for f in *.ucas; do UnrealPak $f -List | grep 'LogIoStore: Display: "' > ~/temp/ff7rebirth/pak_contents/$f.txt; done
        grep -lr '/End/Content/Sound' | sort | sed 's/.ucas.txt$/.utoc/g' > ../sound_ucas_files.txt

    Tool for extracting IoStore (.pak + .ucas/.utoc) packages (results in .uasset files):
    https://github.com/trumank/retoc

    Example::

        for f in $(cat ~/temp/ff7rebirth/sound_ucas_files.txt); do
            num=$(echo $f | cut -d- -f1); ~/opt/retoc/retoc unpack $f ~/temp/ff7rebirth/extracted/$num/;
        done

    """

    path = Positional(nargs='+', type=IPath(resolve=True), help='Path to the .uexp file to convert')
    output = Option('-o', metavar='PATH', help='Output directory (default: same as input directory)')
    vgmstream = Option(
        metavar='PATH', type=FILE, help='Path to the vgmstream.exe or vgmstream-cli executable that should be used'
    )

    verbose = Counter('-v', help='Increase logging verbosity (can specify multiple times)')

    def _init_command_(self):
        from ds_tools.logging import init_logging

        init_logging(self.verbose, log_path=None)

    # region Path Attributes

    @cached_property
    def _vgmstream_path(self) -> str:
        if self.vgmstream:
            return self.vgmstream.as_posix()
        elif os.name == 'nt':
            return 'vgmstream.exe'
        else:
            return 'vgmstream-cli'

    @cached_property
    def _out_dir(self) -> Path | None:
        return validate_dir(self.output, '--output/-o')

    # endregion

    def main(self):
        # TODO: It seems like tqdm leaves terminals in a bad state...
        paths = self._get_target_files()
        with tqdm(total=len(paths), unit='files', smoothing=0.1, maxinterval=1) as prog_bar:
            for path in paths:
                self.convert(path)
                prog_bar.update()

    def _get_target_files(self):
        return [
            path
            for path in iter_sorted_files(self.path)
            if not (path.parent.name == 'Build' and path.name.endswith('_Voice__Pack.uasset'))
        ]

    def convert(self, path: Path):
        asset = AudioAsset(path)
        if not asset.extension:
            return

        if asset.extension == '.ogg':
            asset.save(self._out_dir)
        else:
            asset.convert(self._vgmstream_path, self._out_dir)


def validate_dir(path: str | None, arg_info: str) -> Path | None:
    if path is None:
        return None
    out_dir = Path(path).expanduser().resolve()
    if not out_dir.exists():
        out_dir.mkdir(parents=True)
    elif not out_dir.is_dir():
        raise ValueError(f'Invalid {arg_info} directory: {out_dir.as_posix()}')
    return out_dir


class AudioAsset:
    def __init__(self, path: Path):
        self.path = path

    @cached_property
    def _sound_subdir(self) -> str | None:
        if self.path.parent.name != 'Sound':
            return self.path.parent.as_posix().rsplit('/Sound/', 1)[1]
        else:
            return None

    def save(self, out_dir: Path = None) -> Path:
        if out_dir:
            if self._sound_subdir:
                out_dir /= self._sound_subdir
            out_dir.mkdir(parents=True, exist_ok=True)
            dst_path = out_dir.joinpath(self.path.with_suffix(self.extension).name)
        else:
            dst_path = self.path.with_suffix(self.extension)

        log.log(19, f'Writing {dst_path.as_posix()}')
        dst_path.write_bytes(self._slice_and_format[0])
        return dst_path

    def convert(self, vgmstream_path: str, out_dir: Path = None) -> list[Path]:
        if not out_dir:
            out_dir = self.path.parent
        elif self._sound_subdir:
            out_dir /= self._sound_subdir
            out_dir.mkdir(parents=True, exist_ok=True)

        with TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            tmp_path = tmp_dir.joinpath(self.path.with_suffix(self.extension).name)
            log.debug(f'Saving intermediate file: {tmp_path.as_posix()}')
            tmp_path.write_bytes(self._slice_and_format[0])

            os.chdir(tmp_dir)  # The ?n name ends up using the full provided input path, not just the name

            if self._convert_to_wav(vgmstream_path, tmp_path):
                wav_paths = sorted(tmp_dir.glob('*.wav'))
                if len(wav_paths) >= 10:
                    out_dir /= tmp_path.stem
                    out_dir.mkdir(parents=True, exist_ok=True)
                return self._convert_to_flac(wav_paths, out_dir)
            else:
                return []

    @classmethod
    def _convert_to_wav(cls, vgmstream_path: str, xab_path: Path) -> bool:
        cmd = [vgmstream_path, xab_path.name, '-S0']
        if xab_path.suffix == '.sab':
            cmd.append('-i')  # Convert without looping

        cmd += ['-o', f'{xab_path.stem}#?s#?n.wav']
        try:
            check_output(cmd, encoding='utf-8')
        except CalledProcessError as e:
            log.error(f'Error converting {xab_path.as_posix()} to WAV: {e}')
            return False
        else:
            return True

    @classmethod
    def _convert_to_flac(cls, wav_paths: list[Path], out_dir: Path) -> list[Path]:
        if (n_files := len(wav_paths)) <= 3:
            return [p for path in wav_paths if (p := _wav_to_flac(path, out_dir))]

        log.debug(f'Using thread pool for {n_files} WAVs')
        with ThreadPoolExecutor(max_workers=min(n_files, 4)) as executor:
            futures = {executor.submit(_wav_to_flac, wp, out_dir): wp for wp in wav_paths}
            return [p for f in as_completed(futures) if (p := f.result())]

    # region Load raw

    @cached_property
    def extension(self) -> str | None:
        try:
            return self._slice_and_format[1]
        except ValueError as e:
            log.error(f'{e} for {self.path.as_posix()}')
            return None

    @cached_property
    def _slice_and_format(self) -> tuple[bytes, str]:
        return self._get_slice_and_format()

    def _get_slice_and_format(self) -> tuple[bytes, str]:
        log.debug(f'Reading {self.path.as_posix()}')
        data = self.path.read_bytes()
        for header, ext in HEADER_EXT_MAP.items():
            try:
                start = data.index(header)
            except ValueError:
                continue

            size_pos = start - 8
            size, z_size = SIZE.unpack(data[size_pos:start])
            if size != z_size:
                raise ValueError(f'Unexpected {size=} / {z_size=} mismatch')

            end = start + size
            return data[start:end], ext

            # The below may have worked for .uexp files, but it doesn't work for .uasset files
            # if ext == '.ogg':
            #     return data[start:], ext
            # else:
            #     return data[start:-4], ext

        raise ValueError('Audio header not found')

    # endregion


def _wav_to_flac(src_path: Path, out_dir: Path) -> Path | None:
    out_path = out_dir.joinpath(src_path.with_suffix('.flac').name)
    log.debug(f'Converting to FLAC: {src_path.as_posix()}')
    try:
        check_output(['ffmpeg', '-i', src_path.as_posix(), out_path.as_posix()], stderr=PIPE)
    except CalledProcessError as e:
        log.error(f'Error converting {src_path.as_posix()} to FLAC: {e}')
        return None
    else:
        log.log(19, f'Converted {out_path.as_posix()}')
        return out_path


if __name__ == '__main__':
    main()
