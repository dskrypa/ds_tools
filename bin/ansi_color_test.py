#!/usr/bin/env python3

import sys
from argparse import ArgumentParser
from pathlib import Path

sys.path.append(Path(__file__).expanduser().resolve().parents[1].as_posix())
from ds_tools.output.color import colored, HEX_COLORS_REVERSE

ATTRS = [
    "bold", "dim", "underlined", "blink", "reverse", "hidden", "reset",
    "res_bold", "res_dim", "res_underlined", "res_blink", "res_reverse", "res_hidden"
]


def parser():
    parser = ArgumentParser(description="Tool for testing ANSI colors")
    parser.add_argument("--text", "-t", help="Text to be displayed (default: the number of the color being shown)")
    parser.add_argument("--color", "-c", help="Text color to use (default: cycle through 0-256)")
    parser.add_argument("--background", "-b", help="Background color to use (default: None)")
    parser.add_argument("--attr", "-a", choices=ATTRS, help="Background color to use (default: None)")
    parser.add_argument("--all", "-A", action="store_true", help="Show all forground and background colors (only when no color/background is specified)")
    mparser = parser.add_mutually_exclusive_group()
    mparser.add_argument("--basic", "-B", action="store_true", help="Display colors without the 38;5; prefix (cannot be combined with other args)")
    mparser.add_argument("--hex", "-H", action="store_true", help="Display colors by hex value (cannot be combined with other args)")
    return parser


def main():
    args = parser().parse_args()
    if (args.color or args.background) and args.all:
        raise ValueError("--all / -A can only be specified without --color / -c and --background / -b")

    if args.basic:
        nums = []
        for i in range(256):
            nums.append(colored("{:3d}".format(i), prefix=i))
            if i % 16 == 15:
                print(" ".join(nums))
                nums = []
    elif args.hex:
        hexs, nums = [], []
        for i, (hex, num) in enumerate(sorted(HEX_COLORS_REVERSE.items())):
            hexs.append(colored(hex, hex))
            nums.append(colored("{:>3}".format(num), num))
            if i % 16 == 15:
                print(" ".join(hexs), "|", " ".join(nums))
                hexs, nums = [], []
    elif args.color and args.background:
        attrs = (args.attr,) if args.attr else ATTRS
        for attr in attrs:
            text = args.text or "{}: example text".format(attr)
            print(colored(text, args.color, args.background, attr))
    elif args.color:
        if args.text:
            for i in range(256):
                print(colored("{:3d}: {}".format(i, args.text), args.color, i, args.attr))
        else:
            nums = []
            for i in range(256):
                nums.append(colored("{:3d}".format(i), args.color, i, args.attr))
                if i % 16 == 15:
                    print(" ".join(nums))
                    nums = []
    elif args.background:
        if args.text:
            for i in range(256):
                print(colored("{:3d}: {}".format(i, args.text), i, args.background, args.attr))
        else:
            nums = []
            for i in range(256):
                nums.append(colored("{:3d}".format(i), i, args.background, args.attr))
                if i % 16 == 15:
                    print(" ".join(nums))
                    nums = []
    elif args.all:
        if args.text:
            for c in range(256):
                for b in range(256):
                    print(colored("{:3d},{:3d}: {}".format(c, b, args.text), c, b, args.attr))
        else:
            nums = []
            for c in range(256):
                for b in range(256):
                    nums.append(colored("{:3d},{:3d}".format(c, b), c, b, args.attr))
                    if b % 16 == 15:
                        print(" ".join(nums))
                        nums = []
                print()
    else:
        nums = []
        for i in range(256):
            nums.append(colored("{:3d}".format(i), i, None, args.attr))
            if i % 16 == 15:
                print(" ".join(nums))
                nums = []


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print()
