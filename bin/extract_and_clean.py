#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging
import os
import re
import sys
from pathlib import Path

sys.path.append(Path(__file__).expanduser().resolve().parents[1].as_posix())
from ds_tools.argparsing import ArgParser
from ds_tools.core import now, DATE_FMT
from ds_tools.logging import LogManager
from ds_tools.shell import exec_local

log = logging.getLogger("ds_tools.{}".format(__name__))


def parser():
    parser = ArgParser(description="Extract and cleanup album zips")
    parser.add_argument("path", help="Directory to process")
    parser.include_common_args("verbosity")
    return parser


def main():
    args = parser().parse_args()
    LogManager.create_default_logger(args.verbose, log_path=None)

    src_dir = Path(args.path).expanduser().resolve()
    zip_dir = src_dir.parent.joinpath("extracted_{}".format(now(DATE_FMT)))

    for artist in src_dir.iterdir():
        if artist.is_dir():
            dest = zip_dir.joinpath(artist.stem)
            if not dest.exists():
                os.makedirs(dest.as_posix())

            for f in artist.iterdir():
                if f.suffix in (".7z", ".zip"):
                    log.info("Extracting: {}".format(f.as_posix()))
                    exec_local("7z", "x", f.as_posix(), "-o{}".format(artist.as_posix()), mode="raw", raise_nonzero=True)
                    f.rename(dest.joinpath(f.name))
                elif f.suffix == ".rar":
                    log.info("Extracting: {}".format(f.as_posix()))
                    exec_local("unrar", "x", f.as_posix(), artist.as_posix(), mode="raw", raise_nonzero=True)
                    f.rename(dest.joinpath(f.name))
                else:
                    log.info("Skipping non-archive: {}".format(f.as_posix()))
        else:
            log.info("Skipping non-directory at artist level: {}".format(artist.as_posix()))

    for artist in src_dir.iterdir():
        if artist.is_dir():
            for album in artist.iterdir():
                if album.is_dir():
                    for f in album.iterdir():
                        if f.suffix == ".url":
                            log.info("Deleting: {}".format(f.as_posix()))
                            f.unlink()

                    m = re.match("(.*)\[www.*\.com\]$", album.name)
                    if m:
                        cleaned = album.with_name(m.group(1).strip())
                        log.info("Renaming {} -> {}".format(album.as_posix(), cleaned.as_posix()))
                        try:
                            album.rename(cleaned)
                        except OSError as e:
                            log.error(e)
                else:
                    log.info("Skipping non-directory at albumlevel: {}".format(album.as_posix()))
        else:
            log.info("Skipping non-directory at artist level: {}".format(artist.as_posix()))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print()
