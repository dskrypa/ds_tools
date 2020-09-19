#!/usr/bin/env python3

import sys
from pathlib import Path

sys.path.append(Path(__file__).resolve().parents[1].as_posix())
from ds_tools.core.decorate import partitioned_exec


class PartitionTester:
    def __init__(self):
        #TODO: turn in to unit tests
        pass

    @partitioned_exec(3, dict, lambda a, b: a.update(b), 1)
    def test_one(self, seq):
        print('Test one: {}'.format(', '.join(map(str, seq))))
        return {chr(65 + i): i for i in seq}

    @partitioned_exec(4, dict, pos=1)
    def test_two(self, seq):
        print('Test two: {}'.format(', '.join(map(str, seq))))
        return {chr(97 + i): i for i in seq}

    @partitioned_exec(2, list, lambda a, b: a.extend(b), 1)
    def test_three(self, seq):
        print('Test three: {}'.format(', '.join(map(str, seq))))
        return [i * 2 for i in seq]

    @partitioned_exec(4, dict, lambda a, b: a.update(b), 1)
    def test_four(self, seq):
        print('Test four: {}'.format(', '.join(map(str, seq))))
        return {chr(97 + i): i for i in seq}

    @partitioned_exec(2, list, pos=2)
    def test_five(self, fn, seq):
        print('Test five: {}'.format(', '.join(map(str, seq))))
        return [fn(i) for i in seq]


@partitioned_exec(2, list, lambda a, b: a.extend(b))
def test_six(seq, fn):
    print('Test six: {}'.format(', '.join(map(str, seq))))
    return [fn(i) for i in seq]


if __name__ == '__main__':
    pt = PartitionTester()

    print(pt.test_one(range(10)))
    print(pt.test_two(range(11)))
    print(pt.test_one(range(8)))
    print(pt.test_three(range(8)))
    print(pt.test_four(range(11)))
    print(pt.test_five(lambda a: a * 3, range(11)))
    print(test_six(range(11), lambda a: a + 10))
