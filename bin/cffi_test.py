#!/usr/bin/env python

import struct
from io import BytesIO

import cffi


def main():
    simple_test()
    print()
    complex_test()
    print()
    poorly_defined_struct_test()


def poorly_defined_struct_test():
    print('========== Poorly Defined Struct Test ==========')
    point = struct.Struct('dd')
    x = struct.Struct('d')
    y = struct.Struct('d')
    point_bytes = point.pack(12.34, 56.78)

    pnt = point.unpack(point_bytes)
    print('via point.unpack: {}'.format(pnt))

    pnt = (x.unpack(point_bytes[:8])[0], y.unpack(point_bytes[8:])[0])
    print('via separate unpacks: {}'.format(pnt))

    init = """Test init:
    point = struct.Struct('dd')
    x = struct.Struct('d')
    y = struct.Struct('d')
    point_bytes = point.pack(12.34, 56.78)
    """
    tests = """
    >>> %timeit pnt = point.unpack(point_bytes)
    131 ns ± 0.357 ns per loop (mean ± std. dev. of 7 runs, 10000000 loops each)
    
    >>> %timeit pnt = (x.unpack(point_bytes[:8])[0], y.unpack(point_bytes[8:])[0])
    410 ns ± 0.496 ns per loop (mean ± std. dev. of 7 runs, 1000000 loops each)
    
    Note: The latter example is how it ends up being done by flatbuffers!
    """

    print(init)
    print('\nTest Results:\n')
    print(tests)


def complex_test():
    print('========== Multi-Type Struct Test ==========')
    def encode(x, y, s):
        complex_struct = struct.Struct('dd{}s'.format(len(s)))
        return complex_struct, complex_struct.pack(x, y, s)

    complex_struct, complex_bytes = encode(12.34, 56.78, b'test')
    complex_len = len(complex_bytes)
    ffi = cffi.FFI()
    ffi.cdef("""
        typedef struct Complex {
            double x, y;
            char s[128];
        } complex_t;
    """)

    complex_1 = ffi.new('complex_t*')
    ffi.memmove(complex_1, complex_bytes, complex_len)
    print('via ffi.memmove: ({}, {}, {!r})'.format(complex_1.x, complex_1.y, ffi.string(complex_1.s)))

    x, y, s = complex_struct.unpack(complex_bytes)
    print('via struct.unpack: ({}, {}, {!r})'.format(x, y, s))

    init = """Test init:
    def encode(x, y, s):
        complex_struct = struct.Struct('dd{}s'.format(len(s)))
        return complex_struct, complex_struct.pack(x, y, s)

    complex_struct, complex_bytes = encode(12.34, 56.78, b'test')
    complex_len = len(complex_bytes)
    """
    test_1 = """
    >>> complex_1 = ffi.new('complex_t*')
    >>> mem_move = ffi.memmove; ffi_str = ffi.string
    >>> %timeit mem_move(complex_1, complex_bytes, complex_len); val = (complex_1.x, complex_1.y, ffi_str(complex_1.s))
    683 ns ± 4.92 ns per loop (mean ± std. dev. of 7 runs, 1000000 loops each)
    """
    test_2a = """
    >>> %timeit val = complex_struct.unpack(complex_bytes)
    157 ns ± 1.85 ns per loop (mean ± std. dev. of 7 runs, 10000000 loops each)
    """
    test_2b = """
    >>> complex_unpack = complex_struct.unpack
    >>> %timeit val = complex_unpack(complex_bytes)
    154 ns ± 2.33 ns per loop (mean ± std. dev. of 7 runs, 10000000 loops each)
    """

    print(init)
    print('\nTest Results:\n')
    print(test_1)
    print(test_2a)
    print(test_2b)


def simple_test():
    print('========== Simple Point Test ==========')
    point = struct.Struct('dd')
    point_bytes = point.pack(12.34, 56.78)
    point_len = len(point_bytes)
    ffi = cffi.FFI()
    ffi.cdef("""
        typedef struct Point {
            double x, y;
        } point_t;
    """)

    points_1 = ffi.new('point_t[]', 1)
    BytesIO(point_bytes).readinto(ffi.buffer(points_1))
    point_1 = points_1[0]
    print('point_1 via BytesIO.readinto: ({}, {})'.format(point_1.x, point_1.y))

    points_2 = ffi.from_buffer('point_t[]', point_bytes)
    point_2 = points_2[0]
    print('point_2 via ffi.from_buffer: ({}, {})'.format(point_2.x, point_2.y))

    point_3 = ffi.new('point_t*')
    ffi.memmove(point_3, point_bytes, point_len)
    print('point_3 via ffi.memmove: ({}, {})'.format(point_3.x, point_3.y))

    p4x, p4y = point.unpack(point_bytes)
    print('point_4 via struct.unpack: ({}, {})'.format(p4x, p4y))

    init = """Test init:
    >>> point = struct.Struct('dd')
    >>> point_bytes = point.pack(12.34, 56.78)
    >>> point_len = len(point_bytes)
    """
    test_1 = """
    >>> points_1 = ffi.new('point_t[]', 1)
    >>> %timeit BytesIO(point_bytes).readinto(ffi.buffer(points_1)); point_1 = points_1[0]; pnt = (point_1.x, point_1.y)
    561 ns ± 7.79 ns per loop (mean ± std. dev. of 7 runs, 1000000 loops each)
    """
    test_2 = """
    >>> %timeit points_2 = ffi.from_buffer('point_t[]', point_bytes); point_2 = points_2[0]; pnt = (point_2.x, point_2.y)
    794 ns ± 0.845 ns per loop (mean ± std. dev. of 7 runs, 1000000 loops each)
    """
    test_3a = """
    >>> point_3 = ffi.new('point_t*')
    >>> %timeit ffi.memmove(point_3, point_bytes, len(point_bytes)); pnt = (point_3.x, point_3.y)
    488 ns ± 5.69 ns per loop (mean ± std. dev. of 7 runs, 1000000 loops each)
    """
    test_3b = """
    >>> point_3 = ffi.new('point_t*')
    >>> %timeit ffi.memmove(point_3, point_bytes, point_len); pnt = (point_3.x, point_3.y)
    448 ns ± 3.82 ns per loop (mean ± std. dev. of 7 runs, 1000000 loops each)
    """
    test_3c = """
    >>> point_3 = ffi.new('point_t*')
    >>> mem_move = ffi.memmove
    >>> %timeit mem_move(point_3, point_bytes, point_len); pnt = (point_3.x, point_3.y)
    397 ns ± 2.66 ns per loop (mean ± std. dev. of 7 runs, 1000000 loops each)
    """
    test_4 = """
    >>> %timeit pnt = point.unpack(point_bytes)
    136 ns ± 0.831 ns per loop (mean ± std. dev. of 7 runs, 10000000 loops each)
    """

    print(init)
    print('\nTest Results:\n')
    print(test_1)
    print(test_2)
    print(test_3a)
    print(test_3b)
    print(test_3c)
    print(test_4)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print()
