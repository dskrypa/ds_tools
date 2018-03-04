#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys


def diamond():
    """
    Imitates the <> diamond operator from Perl.

    Note: On Windows, EOF = [ctrl]+[z] (followed by [enter])

    :return: Generator that yields lines (str) from stdin or the files with the names in sys.argv
    """
    nlstrip = lambda s: s.rstrip("\n")

    if len(sys.argv) == 1:
        yield from map(nlstrip, sys.stdin.readlines())
    else:
        for file in sys.argv[1:]:
            if file == "-":
                yield from map(nlstrip, sys.stdin.readlines())
            else:
                with open(file, "r") as f:
                    yield from map(nlstrip, f.readlines())


def test_diamond():
    for line in diamond():
        print(line)


if __name__ == "__main__":
    test_diamond()
