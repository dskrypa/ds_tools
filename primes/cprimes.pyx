
"""
Rebuild:
./setup.py build_ext --inplace && cython -a ./cprimes.pyx
"""

import gzip
import os
from array import array
from bisect import bisect_left
from libc.math cimport sqrt

PRIMES = [2,3,5,7,11,13,17,19,23,29,31,37,41,43,47,53,59,61,67,71,73,79,83,89,97,101,103,107,109,113,127,131,137,139]


class PrimeFinder:
    def __init__(self, cache_file=None):
        self.primes = array("Q")
        if cache_file is not None:
            if os.path.exists(cache_file):
                with gzip.open(cache_file, "rb") as f:
                    self.primes.frombytes(f.read())
        if not self.primes:
            self.primes.extend(PRIMES)
        self.non_contiguous_primes = set()

    def save(self, save_path):
        with gzip.open(save_path, "wb") as f:
            f.write(self.primes.tobytes())

    def next_prime(self):
        cdef unsigned long long n, last, i
        primes = self.primes[1:]
        n = primes[-1]
        while True:
            n += 2
            last = (<unsigned long long>sqrt(n)) + 1
            for i in primes:
                if i > last:
                    self.primes.append(n)
                    return n
                elif n % i == 0:
                    break

    def __iter__(self):
        yield from self.primes
        while True:
            yield self.next_prime()

    def __contains__(self, unsigned long long item):
        i = bisect_left(self.primes, item)
        return i < len(self.primes)

    def _is_known_prime(self, unsigned long long n):
        return (n in self) or (n in self.non_contiguous_primes)

    def _is_prime_via_known_sieve(self, unsigned long long n):
        cdef unsigned long long last, i
        if n % 2 == 0:
            return False
        elif self._is_known_prime(n):
            return True

        last = (<unsigned long long>sqrt(n)) + 1
        for i in self.primes[1:]:
            if i > last:
                self.non_contiguous_primes.add(n)
                return True
            elif n % i == 0:
                return False
        raise TooFewPrimesKnown(last, n, i)

    def is_prime_via_sieve(self, unsigned long long n):
        """This takes too long if more primes than are known need to be computed"""
        cdef unsigned long long last, i
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

    def is_prime_via_brute_force(self, unsigned long long n):
        """
        First uses the Sieve of Eratosthenes with primes that have already been computed, then falls back on testing
        each odd integer between the last known prime and int(sqrt(n))+1.

        :param int n: An integer to test for primality
        :return bool: True if the given number is prime, False otherwise
        """
        cdef unsigned long long last, i
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
        fmt = "Too few primes known to determine primality of sqrt({:,d})+1 = {:,d} via pure sieve; last known prime: {:,d}"
        print(fmt.format(n, last, i))
