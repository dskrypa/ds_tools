#!/usr/bin/env python3

import argparse
import gzip
import math
import os
import time
from array import array
from bisect import bisect_left

from cprimes import PrimeFinder32, PrimeFinder64    # PrimeFinder as PrimeFinderC,

PRIMES = [2,3,5,7,11,13,17,19,23,29,31,37,41,43,47,53,59,61,67,71,73,79,83,89,97,101,103,107,109,113,127,131,137,139]


class PrimeFinder:
    def __init__(self, cache_file=None):
        self.primes = array('Q')
        if cache_file is not None:
            if os.path.exists(cache_file):
                with gzip.open(cache_file, 'rb') as f:
                    self.primes.frombytes(f.read())
        if not self.primes:
            self.primes.extend(PRIMES)
        self.non_contiguous_primes = set()
        self.values_checked = 0

    def save(self, save_path):
        with gzip.open(save_path, 'wb') as f:
            f.write(self.primes.tobytes())

    def next_prime(self):
        n = self.primes[-1]
        while True:
            n += 2
            last = int(math.sqrt(n)) + 1
            for i in self.primes[1:]:
                if i > last:
                    self.primes.append(n)
                    return n
                elif n % i == 0:
                    break

    def find_new_primes(self, count):
        primes = self.primes[1:]            # can skip 2 because it is guaranteed to be known, and we always += 2
        n = primes[-1]
        c = 0
        while c < count:
            n += 2
            last = int(math.sqrt(n)) + 1
            for i in primes:
                if i > last:
                    self.primes.append(n)
                    c += 1
                    break
                elif n % i == 0:
                    break

    def __iter__(self):
        yield from self.primes
        while True:
            yield self.next_prime()

    def __contains__(self, item):
        i = bisect_left(self.primes, item)
        return i < len(self.primes)

    def _is_known_prime(self, n):
        return (n in self) or (n in self.non_contiguous_primes)

    def _is_prime_via_known_sieve(self, n):
        if n % 2 == 0:
            return False
        elif self._is_known_prime(n):
            return True

        i = 3
        last = int(math.sqrt(n)) + 1
        for i in self.primes[1:]:
            if i > last:
                self.non_contiguous_primes.add(n)
                return True
            elif n % i == 0:
                return False
        raise TooFewPrimesKnown(last, n, i)

    def is_prime_via_sieve(self, n):
        """This takes too long if more primes than are known need to be computed"""
        try:
            return self._is_prime_via_known_sieve(n)
        except TooFewPrimesKnown as e:
            last = e.last

        while True:
            i = self.next_prime()
            if i > last:
                self.non_contiguous_primes.add(n)
                return True
            elif n % i == 0:
                return False

    def is_prime_via_brute_force(self, n):
        """
        First uses the Sieve of Eratosthenes with primes that have already been computed, then falls back on testing
        each odd integer between the last known prime and int(sqrt(n))+1.

        :param int n: An integer to test for primality
        :return bool: True if the given number is prime, False otherwise
        """
        try:
            return self._is_prime_via_known_sieve(n)
        except TooFewPrimesKnown as e:
            last = e.last

        for i in range(self.primes[-1] + 2, last, 2):
            if n % i == 0:
                return False
        self.non_contiguous_primes.add(n)
        return True

    is_prime = is_prime_via_brute_force


class TooFewPrimesKnown(Exception):
    """Exception to be raised when too few primes are known - only meant to be used internally"""
    def __init__(self, last, n, i):
        self.last = last
        fmt = 'Too few primes known to determine primality of sqrt({:,d})+1 = {:,d} via pure sieve; last known prime: {:,d}'
        print(fmt.format(n, last, i))


def main():
    parser = argparse.ArgumentParser(description='Prime Finder')
    parser.add_argument('--mode', '-m', choices=('py', 'c'), help='Prime finder mode', required=True)
    mgroup = parser.add_mutually_exclusive_group()
    mgroup.add_argument('--count', '-c', type=int, help='Find the given number of prime numbers')
    mgroup.add_argument('--find_new', '-f', type=int, help='Find the given number of prime numbers')
    mgroup.add_argument('--test', '-t', type=int, help='Test the given value to see if it is prime or not')
    mgroup.add_argument('--save', '-s', type=int, help='Number of prime numbers to find to cache to a file; if the cache file already exists, this many additional primes will be appended to it')

    bgroup = parser.add_mutually_exclusive_group()
    bgroup.add_argument('--prime_cache32', '-p32', help='Path of 32 bit integer prime number cache file to use if it exists')
    bgroup.add_argument('--prime_cache64', '-p64', help='Path of 64 bit integer prime number cache file to use if it exists')
    args = parser.parse_args()

    if args.mode == 'py':
        prime_cache = args.prime_cache32 or args.prime_cache64
        pf = PrimeFinder(prime_cache)
    else:
        if args.prime_cache64:
            pf = PrimeFinder64(args.prime_cache64)
            prime_cache = args.prime_cache64
        elif args.prime_cache32:
            pf = PrimeFinder32(args.prime_cache32)
            prime_cache = args.prime_cache32
        else:
            raise ValueError('A prime cache file is required for C mode')

    print('Most recent prime: {:,d}'.format(pf.primes[-1]))

    start = time.time()

    if args.count:
        pfi = iter(pf)
        for i in range(args.count):
            next(pfi)
        finish = time.time()
    elif args.find_new:
        pf.find_new_primes(args.find_new)
        finish = time.time()
        print('Most recent prime: {:,d}'.format(pf.primes[-1]))
    elif args.test:
        result = pf.is_prime(args.test)
        finish = time.time()
        print('Is {:,d} prime? {} (values checked: {:,d})'.format(args.test, result, pf.values_checked))
    elif args.save:
        if not prime_cache:
            raise ValueError('--prime_cache / -p PATH is required to save results to a file')
        pf.find_new_primes(args.save)
        finish = time.time()
        print('Most recent prime: {:,d}'.format(pf.primes[-1]))
        pf.save(prime_cache)
    else:
        raise ValueError('Unexpected option')

    if prime_cache:
        print('{:,d} prime numbers are currently cached'.format(len(pf.primes)))

    print('Took {:,f} seconds'.format(finish - start))


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt as e:
        print()
