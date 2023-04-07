#!/usr/bin/env python

import logging
from pathlib import Path
from subprocess import check_output, CalledProcessError, PIPE
from typing import Optional

from cli_command_parser import Command, Positional, Option, Flag, Counter, main, inputs

from ds_tools.__version__ import __author_email__, __version__  # noqa

log = logging.getLogger(__name__)
HEADER_EXT_MAP = {b'mabf': '.mab', b'sabf': '.sab', b'OggS': '.ogg'}


class UEXPAudioConverter(Command, description='UEXP Audio Converter'):
    path = Positional(nargs='+', type=inputs.Path(resolve=True), help='Path to the .uexp file to convert')
    output = Option('-o', metavar='PATH', help='Output directory (default: same as input directory)')
    wav_output = Option('-w', metavar='PATH', help='WAV output directory (default: same as input directory)')
    flac_output = Option('-f', metavar='PATH', help='FLAC output directory (default: same as input directory)')
    mp3_output = Option('-m', metavar='PATH', help='MP3 output directory (default: same as input directory)')
    mp3 = Flag('-M', help='Convert to MP3 in addition to FLAC')
    verbose = Counter('-v', help='Increase logging verbosity (can specify multiple times)')

    def _init_command_(self):
        from ds_tools.logging import init_logging

        init_logging(self.verbose, log_path=None)

    def main(self):
        audio_dir = validate_dir(self.output, '--output/-o')
        wav_dir = validate_dir(self.wav_output, '--wav-output/-w')
        flac_dir = validate_dir(self.flac_output, '--flac-output/-f')
        mp3_dir = validate_dir(self.mp3_output, '--mp3-output/-m')

        for path in self.path:
            dst_path = uexp_to_audio(path, audio_dir)
            if dst_path is not None and dst_path.suffix in {'.mab', '.sab'}:
                if wav_paths := xab_to_wav(dst_path, wav_dir):
                    log.info(f'Converted {dst_path.as_posix()} to {len(wav_paths)} WAV files')
                    for wav_path in wav_paths:
                        wav_to_flac(wav_path, flac_dir)
                        if self.mp3:
                            wav_to_mp3(wav_path, mp3_dir)


def validate_dir(path: Optional[str], arg_info: str) -> Optional[Path]:
    if path is None:
        return None
    out_dir = Path(path).expanduser().resolve()
    if not out_dir.exists():
        out_dir.mkdir(parents=True)
    elif not out_dir.is_dir():
        raise ValueError(f'Invalid {arg_info} directory: {out_dir.as_posix()}')
    return out_dir


def wav_to_flac(src_path: Path, out_dir: Path = None) -> Optional[Path]:
    out_base = out_dir or src_path.parent
    out_path = out_base.joinpath(src_path.with_suffix('.flac').name)
    log.debug(f'Converting to FLAC: {src_path.as_posix()}')
    try:
        check_output(['ffmpeg', '-i', src_path.as_posix(), out_path.as_posix()], stderr=PIPE)
    except CalledProcessError as e:
        log.error(f'Error converting {src_path.as_posix()} to FLAC: {e}')
        return None
    else:
        log.info(f'Converted {out_path.as_posix()}')
        return out_path


def wav_to_mp3(src_path: Path, out_dir: Path = None) -> Optional[Path]:
    out_base = out_dir or src_path.parent
    out_path = out_base.joinpath(src_path.with_suffix('.mp3').name)
    try:
        check_output(['ffmpeg', '-i', src_path.as_posix(), '-q:a', '0', out_path.as_posix()], stderr=PIPE)
    except CalledProcessError as e:
        log.error(f'Error converting {src_path.as_posix()} to MP3: {e}')
        return None
    else:
        log.info(f'Converted {out_path.as_posix()}')
        return out_path


def xab_to_wav(src_path: Path, out_dir: Path = None) -> list[Path]:
    cmd = ['vgmstream.exe', src_path.as_posix(), '-S0']
    if src_path.suffix == '.sab':
        cmd.append('-i')

    out_base = out_dir or src_path.parent
    cmd.append('-o')
    cmd.append(out_base.resolve().as_posix() + f'/{src_path.stem}#?s#?n.wav')

    try:
        stdout = check_output(cmd, encoding='utf-8')
    except CalledProcessError as e:
        log.error(f'Error converting {src_path.as_posix()} to WAV: {e}')
        return []
    else:
        stream_names = [
            line.split(':', 1)[1].replace('/', '_').strip()
            for line in stdout.splitlines()
            if line.startswith('stream name:')
        ]
        name = src_path.stem
        return [out_base.joinpath(f'{name}#{n}#{stream_name}.wav') for n, stream_name in enumerate(stream_names, 1)]


def uexp_to_audio(src_path: Path, out_dir: Path = None) -> Optional[Path]:
    try:
        data, ext = get_slice_and_format(src_path.read_bytes())
    except ValueError as e:
        log.error(f'{e} for {src_path.as_posix()}')
    else:
        dst_path = src_path.with_suffix(ext)
        if out_dir is not None:
            dst_path = out_dir.joinpath(dst_path.name)
        log.info(f'Writing {dst_path.as_posix()}')
        dst_path.write_bytes(data)
        return dst_path


def get_slice_and_format(data: bytes):
    for header, ext in HEADER_EXT_MAP.items():
        try:
            start = data.index(header)
        except ValueError:
            pass
        else:
            if ext == '.ogg':
                return data[start:], ext
            else:
                return data[start:-4], ext

    raise ValueError('Audio header not found')


if __name__ == '__main__':
    main()
