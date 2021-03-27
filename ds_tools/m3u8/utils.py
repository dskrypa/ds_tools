import logging
from pathlib import Path
from typing import Optional, Union

from ds_tools.shell import exec_local

log = logging.getLogger(__name__)


class Retries:
    def __init__(self, min: int = 5, max: int = 20, incr: int = 5, per_step: int = 3):
        self.delay = min
        self.max = max
        self.incr = incr
        self.per_step = per_step
        self.step_retries = 0

    def __iter__(self):
        return self

    def __next__(self):
        if self.step_retries >= self.per_step:
            if self.delay < self.max:
                self.step_retries = 0
                self.delay = min(self.delay + self.incr, self.max)
        else:
            self.step_retries += 1
        return self.delay


class Ffmpeg:
    def __init__(
        self, *inputs: Union[str, Path], log_level: str = 'fatal', subs: Optional[str] = None, fmt: str = 'mp4'
    ):
        self.inputs = [i.as_posix() if isinstance(i, Path) else i for i in inputs]
        self.log_level = log_level
        self.subs = subs
        self.format = fmt

    def _cmd(self, out_path: str):
        cmd = [
            'ffmpeg',
            '-loglevel', self.log_level,  # debug, info, warning, fatal
            '-flags', '+global_header',
            '-stats',
            '-protocol_whitelist', 'file,http,https,tcp,tls,crypto',
            '-allowed_extensions', 'ALL',
            # '-reconnect_streamed', '1',
        ]

        if any(path.startswith(('http://', 'https://')) for path in self.inputs):
            cmd.extend((
                # '-thread_queue_size', '2147483647',     # this is the max allowed queue size
                '-thread_queue_size', '128',
                '-timeout', '10000000',
                '-reconnect', '1',
            ))

        for path in self.inputs:
            cmd.extend(('-i', path.as_posix() if isinstance(path, Path) else path))

        cmd.extend((
            '-c:v', 'copy',
            '-c:a', 'copy',
        ))
        if self.subs:
            cmd.extend(('-c:s', self.subs, '-disposition:s:0', 'default'))

        cmd.extend((
            '-bsf:a', 'aac_adtstoasc',
            '-f', self.format,
            out_path
        ))
        return cmd

    def save(self, path: str, log_level: Optional[str] = None):
        if log_level:
            self.log_level = log_level
        print()
        cmd = self._cmd(path)
        code, out, err = exec_local(*cmd, mode='raw', raise_nonzero=True)
        return path
