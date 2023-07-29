#!/usr/bin/env python

from cli_command_parser import Command, Positional, Option, Counter, main


class HexUnpacker(Command, description='View hex data as unpacked structs'):
    data = Positional(nargs='+', help='A hex string')
    offset: int = Option('-o', default=0, help='Offset from the beginning of the data in bytes to start struct matching')
    endian = Option('-e', choices=('big', 'little', 'native'), help='Interpret values with the given endianness')
    verbose = Counter('-v', help='Increase logging verbosity (can specify multiple times)')

    def _init_command_(self):
        from ds_tools.logging import init_logging

        init_logging(self.verbose, log_path=None)

    def main(self):
        from io import BytesIO
        from ds_tools.misc.binary import view_unpacked

        data = ''.join(self.data)
        if not len(data) % 2 == 0:
            raise ValueError('Invalid data - length must be divisible by 2')

        bio = BytesIO()
        for i in range(0, len(data), 2):
            bio.write(bytes.fromhex(data[i: i + 2]))
            # bio.write(int(data[i: i + 2], 16).to_bytes())

        for key, val in view_unpacked(bio.getvalue(), offset=self.offset, endian=self.endian).items():
            print(f'{key}: {val}')


if __name__ == '__main__':
    main()
