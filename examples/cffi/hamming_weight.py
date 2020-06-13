
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
