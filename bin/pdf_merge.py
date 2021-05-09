#!/usr/bin/env python

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, PROJECT_ROOT.joinpath('bin').as_posix())
import _venv  # This will activate the venv, if it exists and is not already active

import logging

from PyPDF2 import PdfFileMerger, PdfFileReader

sys.path.append(PROJECT_ROOT.joinpath('lib').as_posix())
from ds_tools.__version__ import __author_email__, __version__
from ds_tools.argparsing import ArgParser
from ds_tools.core.main import wrap_main
from ds_tools.logging import init_logging

log = logging.getLogger(__name__)


def parser():
    parser = ArgParser(description='Merge 2 or more PDFs')
    parser.add_argument('path', nargs='+', help='Two or more paths of PDF files to merge in the order provided')
    parser.add_argument('--output', '-o', metavar='PATH', help='Output file name', required=True)
    parser.include_common_args('verbosity')
    return parser


@wrap_main
def main():
    args = parser().parse_args()
    init_logging(args.verbose, log_path=None)

    if len(args.path) < 2:
        raise ValueError('At least 2 input files are required')

    merger = PdfFileMerger()
    for path in args.path:
        log.info(f'Adding {path}')
        with open(path, 'rb') as f:
            merger.append(PdfFileReader(f))

    log.info(f'Writing merged PDF: {args.output}')
    merger.write(args.output)


if __name__ == '__main__':
    main()
