#!/usr/bin/env python
# PYTHON_ARGCOMPLETE_OK

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, PROJECT_ROOT.joinpath('bin').as_posix())
import _venv  # This will activate the venv, if it exists and is not already active

sys.path.append(PROJECT_ROOT.as_posix())
from ds_tools.__version__ import __author_email__, __version__
from ds_tools.argparsing import ArgParser
from ds_tools.core.main import wrap_main
from ds_tools.output.color import colored

ATTRS = [
    'bold', 'dim', 'underlined', 'blink', 'reverse', 'hidden', 'reset',
    'res_bold', 'res_dim', 'res_underlined', 'res_blink', 'res_reverse', 'res_hidden'
]


def parser():
    parser = ArgParser(description='Tool for testing ANSI colors')
    parser.add_argument('--text', '-t', help='Text to be displayed (default: the number of the color being shown)')

    parser.add_argument('--color', '-c', help='Text color to use (default: cycle through 0-256)')
    parser.add_argument('--background', '-b', help='Background color to use (default: None)')
    parser.add_argument('--attr', '-a', choices=ATTRS, help='Background color to use (default: None)')

    parser.add_argument('--all', '-A', action='store_true', help='Show all forground and background colors (only when no color/background is specified)')
    parser.add_argument('--limit', '-L', type=int, default=256, help='Range limit')

    mparser = parser.add_mutually_exclusive_group()
    mparser.add_argument('--basic', '-B', action='store_true', help='Display colors without the 38;5; prefix (cannot be combined with other args)')
    mparser.add_argument('--hex', '-H', action='store_true', help='Display colors by hex value (cannot be combined with other args)')

    return parser


@wrap_main
def main():
    args = parser().parse_args()
    if (args.color or args.background) and args.all:
        raise ValueError('--all / -A can only be specified without --color / -c and --background / -b')

    if args.basic:
        nums = []
        for i in range(args.limit):
            nums.append(colored('{:3d}'.format(i), prefix=i))
            if i % 16 == 15:
                print(' '.join(nums))
                nums = []
    elif args.hex:
        from ds_tools.output._colors import HEX_COLORS_REVERSE
        hexs, nums = [], []
        for i, (hex, num) in enumerate(sorted(HEX_COLORS_REVERSE.items())):
            hexs.append(colored(hex, hex))
            nums.append(colored('{:>3}'.format(num), num))
            if i % 16 == 15:
                print(' '.join(hexs), '|', ' '.join(nums))
                hexs, nums = [], []
    elif args.color and args.background:
        attrs = (args.attr,) if args.attr else ATTRS
        for attr in attrs:
            text = args.text or '{}: example text'.format(attr)
            print(colored(text, args.color, args.background, attr))
    elif args.color:
        if args.text:
            for i in range(args.limit):
                print(colored('{:3d}: {}'.format(i, args.text), args.color, i, args.attr))
        else:
            nums = []
            for i in range(args.limit):
                nums.append(colored('{:3d}'.format(i), args.color, i, args.attr))
                if i % 16 == 15:
                    print(' '.join(nums))
                    nums = []
    elif args.background:
        if args.text:
            for i in range(args.limit):
                print(colored('{:3d}: {}'.format(i, args.text), i, args.background, args.attr))
        else:
            nums = []
            for i in range(args.limit):
                nums.append(colored('{:3d}'.format(i), i, args.background, args.attr))
                if i % 16 == 15:
                    print(' '.join(nums))
                    nums = []
    elif args.all:
        if args.text:
            for c in range(args.limit):
                for b in range(args.limit):
                    print(colored('{:3d},{:3d}: {}'.format(c, b, args.text), c, b, args.attr))
        else:
            nums = []
            for c in range(args.limit):
                for b in range(args.limit):
                    nums.append(colored('{:3d},{:3d}'.format(c, b), c, b, args.attr))
                    if b % 16 == 15:
                        print(' '.join(nums))
                        nums = []
                print()
    else:
        nums = []
        for i in range(args.limit):
            nums.append(colored('{:3d}'.format(i), i, None, args.attr))
            if i % 16 == 15:
                print(' '.join(nums))
                nums = []


if __name__ == '__main__':
    main()
