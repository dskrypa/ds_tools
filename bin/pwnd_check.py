#!/usr/bin/env python

import getpass
import logging
import os
import sys
from collections import defaultdict
from csv import DictReader
from hashlib import sha1
from pathlib import Path

sys.path.append(Path(__file__).resolve().parents[1].as_posix())
from ds_tools.argparsing import ArgParser
from ds_tools.logging import init_logging

log = logging.getLogger('ds_tools.{}'.format(__name__))
LIST_PATH = os.path.expanduser('~/etc/pwned-passwords-sha1-ordered-by-count-v4.txt')


def parser():
    parser = ArgParser(description='Utility to check passwords against the list from haveibeenpwned.com')
    parser.add_argument('--pw_list_path', '-p', metavar='PATH', default=LIST_PATH, help='Path to the file that contains the hashed password list (default: %(default)s)')

    src_group = parser.add_mutually_exclusive_group()
    src_group.add_argument('--from_file', '-f', metavar='PATH', help='Path to a KeePass csv file to check')
    src_group.add_argument('--non_confidential', '-C', nargs='+', help='One or more non-confidential passwords to test')

    parser.include_common_args('verbosity', 'dry_run')
    return parser


def main():
    args = parser().parse_args()
    init_logging(args.verbose, log_path=None)

    if args.from_file:
        pws = defaultdict(lambda: defaultdict(set))
        with open(args.from_file, 'r', encoding='utf-8') as f:
            dr = DictReader(f)
            for row in dr:
                try:
                    pws[row['Password']][row['Web Site']].add(row['Login Name'])
                except KeyError as e:
                    raise ValueError('Expected --from_file / -f to be a csv file with a \'Password\' column'.format(args.from_file)) from e
    elif args.non_confidential:
        pws = {pw: {'(provided via cli)': {hashed(pw): pw}} for pw in args.non_confidential}
    else:
        pws = {getpass.getpass(): {'(interactively provided)': {'any'}}}

    pws = {hashed(pw): sites for pw, sites in pws.items()}
    fmt_a = 'Password for site={}, user={} was compromised! (occurrences: {:,d}; rank: {:,d})'
    fmt_b = 'Password {!r} was compromised! (occurrences: {:,d}; rank: {:,d})'
    pw_hashes = sorted(pws.keys())
    with open(args.pw_list_path, 'r') as f:
        for i, line in enumerate(f):
            for pw in pw_hashes:
                if pw in line:
                    sites = pws.pop(pw)
                    pw_hashes = sorted(pws.keys())              # prevent sort on every line
                    count = int(line.split(':')[1].strip())
                    for site, users in sorted(sites.items()):
                        if site == '(provided via cli)':
                            print(fmt_b.format(users[pw], count, i + 1))
                        else:
                            for user in sorted(users):
                                print(fmt_a.format(site, user, count, i + 1))

            if not pw_hashes:
                break

    if pws:
        for pw, sites in sorted(pws.items()):
            for site, users in sorted(sites.items()):
                if site == '(provided via cli)':
                    print('Password {!r} was not included in the list!'.format(users[pw]))
                else:
                    for user in sorted(users):
                        print('Password for site={}, user={} was not in the list!'.format(site, user))


def hashed(pw):
    return sha1(pw.encode('utf-8')).hexdigest().upper()


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print()
