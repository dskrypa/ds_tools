#!/usr/bin/env python
"""
This SHOULD need locks... but my guess is the GIL is making it work without them...
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, PROJECT_ROOT.joinpath('bin').as_posix())
import _venv  # This will activate the venv, if it exists and is not already active

import logging
import time
from random import randint
from threading import RLock, Thread

sys.path.append(PROJECT_ROOT.as_posix())
from ds_tools.argparsing import ArgParser
from ds_tools.core.main import wrap_main
from ds_tools.logging import init_logging

log = logging.getLogger(__name__)

MAX_PERSON_SLICES = 6
MAX_EAT_TIME = 4


def parser():
    parser = ArgParser(description='Extract and cleanup album zips')
    parser.add_argument('--people', '-p', type=int, default=5, help='Number of people to simulate')
    parser.add_argument('--slices', '-s', type=int, default=8, help='Number of slices per pizza')
    parser.include_common_args('verbosity')
    return parser


@wrap_main
def main():
    args = parser().parse_args()
    init_logging(args.verbose, log_path=None)

    parlor = Parlor(args.people, args.slices)
    parlor_thread = Thread(target=parlor.run)
    parlor_thread.start()

    people = [Thread(target=run_person, args=(i, parlor)) for i in range(args.people)]
    for p in people:
        p.start()

    for p in people:
        p.join()
    parlor_thread.join()


class Pizza:
    def __init__(self, slices: int):
        self.slices = slices

    def take_slice(self):
        if self.slices > 0:
            self.slices -= 1
            return self.slices
        return None


class Parlor:
    delivery_time_min = 2
    delivery_time_max = 5

    def __init__(self, customer_count: int, slices: int):
        self.slices_per_pizza = slices
        self.order_pending = False
        self.customer_count = customer_count
        self.pizza = Pizza(slices)

    def place_order(self):
        self.order_pending = True

    def has_active_customers(self) -> bool:
        return self.customer_count > 0

    def make_pizza(self):
        print('Starting to make a pizza')
        self.order_pending = False
        time.sleep(randint(self.delivery_time_min, self.delivery_time_max))
        self.pizza.slices = self.slices_per_pizza

    def run(self):
        while self.has_active_customers():
            if self.order_pending:
                self.make_pizza()
        print('All customers went home')


def run_person(tid: int, parlor: Parlor):
    eaten = 0
    last_slice_msg = -1
    to_eat = randint(1, MAX_PERSON_SLICES)
    while eaten < to_eat:
        if last_slice_msg != eaten:
            print(f'person_{tid}: I\'m hungry!')

        slices_left = parlor.pizza.take_slice()
        if slices_left is None:
            time.sleep(1)
        else:
            print(f'person_{tid}: Got a slice; there are {slices_left} left.')
            eaten += 1
            if slices_left == 0:
                parlor.place_order()
                print(f'person_{tid}: I ordered another pizza')
            time.sleep(randint(1, MAX_EAT_TIME))

    print(f'person_{tid}: I\'m full.')
    parlor.customer_count -= 1


if __name__ == '__main__':
    main()
