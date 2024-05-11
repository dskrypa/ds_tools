#!/usr/bin/env python

import json
import sys

from cli_command_parser import Command, Positional, Flag, main, inputs
import yaml


class Json2Yaml(Command, description='Convert json to yaml'):
    input = Positional(nargs='?', type=inputs.File(allow_dash=True, encoding='utf-8'), help='A file containing JSON')

    def main(self):
        data = self.input.read() if self.input else '\n'.join(sys.stdin.readlines())
        parsed = json.loads(data)
        print(yaml.dump(parsed))


if __name__ == '__main__':
    main()
