#!/usr/bin/env python

import logging

from cli_command_parser import Command, Positional, Option, Counter, main
from PyPDF2 import PdfFileMerger, PdfFileReader

from ds_tools.__version__ import __author_email__, __version__  # noqa

log = logging.getLogger(__name__)


class PDFMerger(Command, description='Merge 2 or more PDFs'):
    path = Positional(nargs=(2, None), help='Two or more paths of PDF files to merge in the order provided')
    output = Option('-o', required=True, metavar='PATH', help='Output file name')
    verbose = Counter('-v', help='Increase logging verbosity (can specify multiple times)')

    def _init_command_(self):
        from ds_tools.logging import init_logging

        init_logging(self.verbose, log_path=None)

    def main(self):
        merger = PdfFileMerger()
        for path in self.path:
            log.info(f'Adding {path}')
            with open(path, 'rb') as f:
                merger.append(PdfFileReader(f))

        log.info(f'Writing merged PDF: {self.output}')
        merger.write(self.output)


if __name__ == '__main__':
    main()
