#!/usr/bin/env python
"""
This was easier than getting a convoluted grep/awk command to work...
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, PROJECT_ROOT.joinpath('bin').as_posix())
import _venv  # This will activate the venv, if it exists and is not already active

import re
from typing import Optional, Any, Callable, Union

from sphinx.ext.intersphinx import fetch_inventory
from cli_command_parser import Command, Option, Flag, main


class Intersphinx(Command):
    url: str = Option('-u', required=True, help='URL pointing to a Sphinx inventory file (objects.inv)')
    find: str = Option('-f', required=True, help='The text to find')
    regex = Flag('-r', help='Treat the given text to find as a regex pattern (default: plain text)')
    ignore_case = Flag('-i', help='Ignore case when attempting to find a match')

    def main(self):
        inventory = self.get_inv()
        matches = self.get_match_func()

        for key, entry_map in inventory.items():
            for entry, (ns, version, uri_path, unknown) in entry_map.items():
                if matches(entry) or matches(uri_path):
                    print(f':{key}:`{entry}` -> {uri_path}')

    def get_inv(self) -> dict[str, dict[str, tuple[str, str, str, str]]]:
        url = self.url
        if not url.endswith('objects.inv'):
            slash = '' if url.endswith('/') else '/'
            url += slash + 'objects.inv'

        class MockConfig:
            intersphinx_timeout: Optional[int] = None
            tls_verify = False
            user_agent = None

        class MockApp:
            srcdir = ''
            config = MockConfig()

            def warn(self, msg: str) -> None:
                print(msg, file=sys.stderr)

        return fetch_inventory(MockApp(), '', url) or {}  # noqa

    def get_match_func(self) -> Callable[[str], Union[bool, Any]]:
        if self.regex:
            args = (re.IGNORECASE,) if self.ignore_case else ()
            return re.compile(self.find, *args).search

        if self.ignore_case:
            to_find = self.find.casefold()

            def matches(text: str) -> bool:
                return to_find in text.casefold()
        else:
            to_find = self.find

            def matches(text: str) -> bool:
                return to_find in text

        return matches


if __name__ == '__main__':
    main()