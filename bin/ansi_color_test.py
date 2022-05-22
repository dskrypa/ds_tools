#!/usr/bin/env python

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, PROJECT_ROOT.joinpath('bin').as_posix())
import _venv  # This will activate the venv, if it exists and is not already active

from cli_command_parser import Command, Option, ParamGroup, Flag, main

sys.path.append(PROJECT_ROOT.as_posix())
from ds_tools.__version__ import __author_email__, __version__
from ds_tools.output.color import colored

ATTRS = [
    'bold', 'dim', 'underlined', 'blink', 'reverse', 'hidden', 'reset',
    'res_bold', 'res_dim', 'res_underlined', 'res_blink', 'res_reverse', 'res_hidden'
]


class AnsiColorTest(Command, description='Tool for testing ANSI colors'):
    text = Option('-t', help='Text to be displayed (default: the number of the color being shown)')
    attr = Option('-a', choices=ATTRS, help='Background color to use (default: None)')
    limit: int = Option('-L', default=256, help='Range limit')

    with ParamGroup(mutually_exclusive=True):
        all = Flag('-A', help='Show all foreground and background colors (only when no color/background is specified)')
        with ParamGroup():  # Both of these can be provided, but neither can be combined with --all / -A
            color = Option('-c', help='Text color to use (default: cycle through 0-256)')
            background = Option('-b', help='Background color to use (default: None)')

    with ParamGroup(mutually_exclusive=True):
        basic = Flag('-B', help='Display colors without the 38;5; prefix (cannot be combined with other args)')
        hex = Flag('-H', help='Display colors by hex value (cannot be combined with other args)')

    def main(self):
        if self.basic:
            for row in range(0, self.limit, 16):
                print(' '.join(colored(f'{i:3d}', prefix=i) for i in range(row, row + 16)))
        elif self.hex:
            from ds_tools.output._colors import HEX_COLORS_REVERSE
            hexs, nums = [], []
            for i, (hex, num) in enumerate(sorted(HEX_COLORS_REVERSE.items())):
                hexs.append(colored(hex, hex))
                nums.append(colored(f'{num:>3}', num))
                if i % 16 == 15:
                    print(' '.join(hexs), '|', ' '.join(nums))
                    hexs, nums = [], []
        elif self.color and self.background:
            attrs = (self.attr,) if self.attr else ATTRS
            for attr in attrs:
                text = self.text or f'{attr}: example text'
                print(colored(text, self.color, self.background, attr))
        elif self.color:
            if self.text:
                for i in range(self.limit):
                    print(colored(f'{i:3d}: {self.text}', self.color, i, self.attr))
            else:
                for row in range(0, self.limit, 16):
                    print(' '.join(colored(f'{i:3d}', self.color, i, self.attr) for i in range(row, row + 16)))
        elif self.background:
            if self.text:
                for i in range(self.limit):
                    print(colored(f'{i:3d}: {self.text}', i, self.background, self.attr))
            else:
                for row in range(0, self.limit, 16):
                    print(' '.join(colored(f'{i:3d}', i, self.background, self.attr) for i in range(row, row + 16)))
        elif self.all:
            if self.text:
                for c in range(self.limit):
                    for b in range(self.limit):
                        print(colored(f'{c:3d},{b:3d}: {self.text}', c, b, self.attr))
            else:
                for c in range(self.limit):
                    for row in range(0, self.limit, 16):
                        print(' '.join(colored(f'{c:3d},{b:3d}', c, b, self.attr) for b in range(row, row + 16)))
                    print()
        else:
            for row in range(0, self.limit, 16):
                print(' '.join(colored(f'{i:3d}', i, None, self.attr) for i in range(row, row + 16)))


if __name__ == '__main__':
    main()
