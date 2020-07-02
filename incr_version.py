#!/usr/bin/env python

import logging
import os
import platform
import re
import sys
import time
from argparse import ArgumentParser
from contextlib import ExitStack
from datetime import datetime
from pathlib import Path
from subprocess import Popen, PIPE
from tempfile import TemporaryDirectory

import psutil

log = logging.getLogger(__name__)

ON_WINDOWS = platform.system().lower() == 'windows'
VERSION_PAT = re.compile(r'^(\s*__version__\s?=\s?)(["\'])(\d{4}\.\d{2}\.\d{2})((?:-\d+)?)\2$')
_NotSet = object()


def main():
    # fmt: off
    parser = ArgumentParser(description='Python project version incrementer (to be run as a pre-commit hook)')
    parser.add_argument('--file', '-f', metavar='PATH', help='The file that contains the version to be incremented')
    parser.add_argument('--encoding', '-e', default='utf-8', help='The encoding used by the version file')
    parser.add_argument('--ignore_staged', '-i', action='store_true', help='Assume already staged version file contains updated version')
    parser.add_argument('--debug', '-d', action='store_true', help='Show debug logging')
    parser.add_argument('--bypass_pipe', '-b', action='store_true', help='Bypass pre-commit\'s stdout pipe when printing the updated version number')
    args = parser.parse_args()
    # fmt: on
    logging.basicConfig(level=logging.DEBUG if args.debug else logging.INFO, format='%(message)s')

    file = VersionFile.find(args.file, args.encoding)
    log.debug('Found file={}'.format(file))

    if file.should_update(args.ignore_staged):
        file.update_version(args.bypass_pipe)
        log.debug('Adding updated version file to the commit...')
        Git.add(file.path.as_posix())


class VersionFile:
    def __init__(self, path: Path, encoding: str = 'utf-8'):
        self.path = path  # type: Path
        self.encoding = encoding
        self._version = _NotSet

    def __repr__(self):
        return '<{}[path={}, version={!r}]>'.format(self.__class__.__name__, self.path.as_posix(), self.version)

    def should_update(self, ignore_staged=False):
        if self.is_modified_and_unstaged():
            fmt = (
                'File={} was modified, but has not been staged to be committed - please `git add` or `git checkout` '
                'this file to proceed'
            )
            raise VersionIncrError(fmt.format(self.path))
        elif self.is_staged():
            if ignore_staged:
                log.info('File={} is already staged in git - assuming it has correct version already'.format(self))
                return False

            log.debug('File={} is already staged in git - checking the staged version number'.format(self))
            if self.staged_version_was_modified():
                log.info('A version update was already staged for {} - exiting'.format(self))
                return False

            log.debug('File={} was already staged with changes, but it does not contain a version update'.format(self))
        else:
            log.debug('File={} is not already staged in git'.format(self))

        # TODO: If parent git process has --amend arg, determine whether the version was updated in the original commit
        # ['C:\\Program Files\\Git\\mingw64\\bin\\git.exe', 'commit', '-m', '<message>', '--amend']
        # ['/.../git', 'commit', '-m', '<message>', '--amend']
        return True

    def is_modified_and_unstaged(self):
        if running_under_precommit():
            return self.path.as_posix() in get_precommit_cached()
        return self.path.as_posix() in Git.get_unstaged_modified()

    def is_staged(self):
        return self.path.as_posix() in Git.get_staged()

    def staged_version_was_modified(self):
        for line in Git.staged_changed_lines(self.path.as_posix()):
            if VERSION_PAT.match(line):
                return True
        return False

    @property
    def version(self):
        if self._version is _NotSet:
            with self.path.open('r', encoding=self.encoding) as f:
                for line in f:
                    m = VERSION_PAT.match(line)
                    if m:
                        self._version = m.group(3) + m.group(4)
                        break
                else:
                    self._version = None
        return self._version

    def contains_version(self):
        return bool(self.version)

    def update_version(self, bypass_pipe):
        found = False
        with TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir).joinpath('tmp.txt')
            log.debug('Writing updated file to temp file={}'.format(tmp_path))
            with ExitStack() as stack:
                f_in = stack.enter_context(self.path.open('r', encoding=self.encoding))
                f_out = stack.enter_context(tmp_path.open('w', encoding=self.encoding, newline='\n'))
                for line in f_in:
                    if found:
                        f_out.write(line)
                    else:
                        m = VERSION_PAT.match(line)
                        if m:
                            found = True
                            new_line = updated_version_line(m.groups(), bypass_pipe)
                            f_out.write(new_line)
                        else:
                            f_out.write(line)
            if found:
                log.debug('Replacing original file={} with modified version'.format(self.path))
                tmp_path.replace(self.path)
            else:
                raise VersionIncrError('No valid version was found in {}'.format(self.path))

    @classmethod
    def find(cls, path, *args, **kwargs):
        if path:
            path = Path(path)
            if path.is_file():
                return cls(path, *args, **kwargs)
            raise VersionIncrError('--file / -f must be the path to a file that exists')

        for root, dirs, files in os.walk(os.getcwd()):
            root = Path(root)
            for file in files:
                path = root.joinpath(file)
                if path.name == '__version__.py':
                    return cls(path, *args, **kwargs)

        setup_path = Path('setup.py')
        if setup_path.is_file():
            return cls(setup_path, *args, **kwargs)
        raise VersionIncrError('Unable to find __version__.py or setup.py - please specify a --file / -f to modify')


def stdout_write(msg, bypass_pipe=False):
    if bypass_pipe:  # Not intended to be called more than once per run.
        with open('con:' if ON_WINDOWS else '/dev/tty', 'w', encoding='utf-8') as stdout:
            stdout.write(msg)
    else:
        sys.stdout.write(msg)
        sys.stdout.flush()


def updated_version_line(groups, bypass_pipe):
    old_date_str = groups[2]
    old_date = datetime.strptime(old_date_str, '%Y.%m.%d').date()
    old_suffix = groups[3]
    old_ver = old_date_str + old_suffix

    today = datetime.now().date()
    today_str = today.strftime('%Y.%m.%d')
    if old_date < today:
        # log.info('Replacing old version={} with new={}'.format(old_ver, today_str))
        stdout_write('\nUpdating version from {} to {}\n'.format(old_ver, today_str), bypass_pipe)
        # print('Updating version from {} to {}'.format(old_ver, today_str), file=sys.stderr)
        return '{0}{1}{2}{1}\n'.format(groups[0], groups[1], today_str)
    else:
        if old_suffix:
            new_suffix = int(old_suffix[1:]) + 1
        else:
            new_suffix = 1
        # log.info('Replacing old version={} with new={}-{}'.format(old_ver, today_str, new_suffix))
        stdout_write('\nUpdating version from {} to {}-{}\n'.format(old_ver, today_str, new_suffix), bypass_pipe)
        # print('Updating version from {} to {}-{}'.format(old_ver, today_str, new_suffix), file=sys.stderr)
        return '{0}{1}{2}-{3}{1}\n'.format(groups[0], groups[1], today_str, new_suffix)


def running_under_precommit():
    this_proc = get_proc()
    pre_commit_cmd = ['env', '.git/hooks/pre-commit']
    return any(proc.cmdline() == pre_commit_cmd for proc in this_proc.parents())


def get_precommit_cached():
    cache_dir = Path('~/.cache/pre-commit/').expanduser().resolve()
    patches = [p.name for p in cache_dir.iterdir() if p.name.startswith('patch')]
    latest = cache_dir.joinpath(max(patches))
    age = time.time() - latest.stat().st_mtime
    if age > 5:
        log.debug('The pre-commit cache file is {:,.3f}s old - ignoring it')
        # TODO: Check pre-commit proc for open files and if the file is open for it, in case another hook ran slowly
        return set()

    diff_match = re.compile(r'diff --git a/(.*?) b/\1$').match
    files = set()
    with latest.open('r', encoding='utf-8') as f:
        for line in f:
            m = diff_match(line)
            if m:
                files.add(m.group(1))
    return files


class Git:
    @classmethod
    def run(cls, *args):
        cmd = ['git']
        cmd.extend(args)
        cmd_str = ' '.join(cmd)
        log.debug('Executing `{}`'.format(cmd_str))
        proc = Popen(cmd, stdout=PIPE, stderr=PIPE)
        stdout, stderr = proc.communicate()
        code = proc.wait()
        if code != 0:
            err_msg_parts = ['Error executing `{}` - exit code={}'.format(cmd_str, code)]
            if stdout:
                err_msg_parts.append('stdout:\n{}'.format(stdout))
            if stderr:
                prefix = '\n' if stdout else ''
                err_msg_parts.append('{}stderr:\n{}'.format(prefix, stderr))
            raise VersionIncrError('\n'.join(err_msg_parts))
        if stderr:
            log.warning('Found stderr for cmd=`{}`:\n{}'.format(cmd_str, stderr))
        return stdout.decode('utf-8')

    @classmethod
    def add(cls, *args):
        return cls.run('add', *args)

    @classmethod
    def get_staged(cls):
        files = cls.run('diff', '--name-only', '--cached').splitlines()
        log.debug('Files staged in the current commit:\n{}'.format('\n'.join(files)))
        return set(files)

    @classmethod
    def has_stashed(cls):
        return bool(cls.run('stash', 'list').strip())

    @classmethod
    def staged_changed_lines(cls, path):
        stdout = cls.run('diff', '--staged', '--no-color', '-U0', path)
        for line in stdout.splitlines():
            if line.startswith('+') and not line.startswith('+++ b/'):
                yield line[1:]

    @classmethod
    def get_unstaged_modified(cls):
        if cls.has_stashed():
            staged = cls.get_staged()
            cmd = ('stash', 'show', '--name-status')
        else:
            staged = set()
            cmd = ('diff', '--name-status')

        files = set()
        for line in cls.run(*cmd).splitlines():
            log.debug('diff line={!r}'.format(line))
            status, file = map(str.strip, line.split(maxsplit=1))
            if status == 'M' and file not in staged:
                files.add(file)
            else:
                log.debug('Ignoring file={!r} with status={!r}'.format(file, status))
        log.debug('Modified files NOT staged in the current commit:\n{}'.format('\n'.join(files)))
        return files


def get_proc():
    pid = os.getpid()
    for proc in psutil.process_iter():
        if proc.pid == pid:
            return proc
    raise VersionIncrError('Unable to find process with pid={} (this process)'.format(pid))


class VersionIncrError(Exception):
    pass


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print()
    except VersionIncrError as e:
        print(e, file=sys.stderr)
        sys.exit(1)
