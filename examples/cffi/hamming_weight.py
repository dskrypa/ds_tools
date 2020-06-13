"""
Example implementation of hamming weight (count the number of 1s in the binary representation of the given number) using
cffi vs pure python.

Performance, from worst to best:

    >>> %timeit hamming_weight_py(2147483638)
    3.45 µs ± 103 ns per loop (mean ± std. dev. of 7 runs, 100000 loops each)

    >>> %timeit bin(2147483638).count('1')
    264 ns ± 0.325 ns per loop (mean ± std. dev. of 7 runs, 1000000 loops each)

    >>> %timeit hamming_weight(2147483638)
    187 ns ± 0.892 ns per loop (mean ± std. dev. of 7 runs, 10000000 loops each)

:author: Doug Skrypa
"""

import cffi

ffi = cffi.FFI()
ffi.cdef('long hamming_weight(long n);')

hamming_weight = ffi.verify("""
long hamming_weight(long n) {
    long c = 0;
    while (n) {
        c++;
        n &= n - 1;
    }
    return c;
}""").hamming_weight


def hamming_weight_py(n):
    c = 0
    while n:
        c += 1
        n &= n - 1
    return c
