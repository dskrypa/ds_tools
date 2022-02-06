#!/usr/bin/env python

import sys
from pathlib import Path

sys.path.insert(0, Path(__file__).resolve().parents[1].joinpath('bin').as_posix())
import _venv  # This will activate the venv, if it exists and is not already active

import json
from argparse import ArgumentParser

import yaml


def main():
    parser = ArgumentParser(description='Convert yaml to json')
    parser.add_argument('path', nargs='?', help='A hex string')
    parser.add_argument('--compact', '-c', action='store_true', help='Print compact json (default: pretty)')
    args = parser.parse_args()

    if not args.path or args.path == '-':
        data = '\n'.join(sys.stdin.readlines())
    else:
        data = Path(args.path).expanduser().resolve().read_text(encoding='utf-8')

    parsed = yaml.safe_load(data)
    if args.compact:
        print(json.dumps(parsed))
    else:
        print(json.dumps(parsed, indent=4, sort_keys=True))


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print()
