#!/usr/bin/env python

import json
import sys

from cli_command_parser import Command, Positional, Flag, main, inputs
import yaml


class Yaml2Json(Command, description='Convert yaml to json'):
    input = Positional(nargs='?', type=inputs.File(allow_dash=True, encoding='utf-8'), help='A hex string')
    compact = Flag('-c', help='Print compact json (default: pretty)')

    def main(self):
        data = self.input.read() if self.input else '\n'.join(sys.stdin.readlines())
        parsed = yaml.safe_load(data)
        if self.compact:
            print(json.dumps(parsed))
        else:
            print(json.dumps(parsed, indent=4, sort_keys=True))


if __name__ == '__main__':
    main()
