"""
:author: Doug Skrypa
"""

import logging
import os
import re
import shlex
import socket
import sys
from subprocess import Popen, PIPE, STDOUT
from threading import Thread
from io import StringIO

from .core import kwmerge
from .output import to_str

__all__ = ["exec_local", "exec_via_ssh", "tee", "psg", "ExternalProcessException"]
log = logging.getLogger(__name__)

SSH = "/usr/bin/ssh"


def exec_local(*cmd, mode="capture", raise_nonzero=False, debug=False, pybuf=False, env=None):
    """
    Execute a shell command in a subprocess

    :param cmd: The command to execute
    :param str mode: Output mode (raw: don't capture; capture: capture stdout/stderr separately; tee: tee output to
        stdout/err and capture; combined: redirect stderr to stdout and capture it)
    :param bool raise_nonzero: Raise an exxception when the exit code is not 0
    :param bool debug: Log full results
    :param bool pybuf: Inverse of the value to be used for the PYTHONUNBUFFERED env variable in the subprocess
    :param dict env: Optional dict of env variables to include in the execution environment
    :return tuple: exit_code, stdout, stderr
    """
    if (len(cmd) == 1) and not isinstance(cmd, str):
        cmd = cmd[0]
    cmd_arr = list(map(str, cmd)) if not isinstance(cmd, str) else shlex.split(cmd)
    cmd_str = " ".join(map(str, cmd_arr))
    log.debug("Executing: {}".format(cmd_str))

    proc_env = kwmerge(os.environ, env, PYTHONUNBUFFERED="1" if not pybuf else "0")

    if mode == "raw":
        p = Popen(cmd_arr, env=proc_env)
        stdout, stderr = None, None
    elif mode == "capture":
        p = Popen(cmd_arr, stdout=PIPE, stderr=PIPE, env=proc_env)
        stdout, stderr = p.communicate()
    elif mode == "combined":
        p = Popen(cmd_arr, stdout=PIPE, stderr=STDOUT, env=proc_env)
        stdout, stderr = p.communicate()    # stderr will be None
    elif mode == "tee":
        p = Popen(cmd_arr, stdout=PIPE, stderr=PIPE, env=proc_env)
        outstr, errstr = StringIO(), StringIO()
        for t in [tee(p.stdout, outstr, sys.stdout), tee(p.stderr, errstr, sys.stderr)]:
            t.join()
        stdout, stderr = outstr.getvalue(), errstr.getvalue()
    elif mode == "binary":
        p = Popen(cmd_arr, stdout=PIPE, stderr=PIPE, env=proc_env)
        stdout, stderr = p.communicate()
        exit_code = p.wait()
        if raise_nonzero and exit_code != 0:
            streams = {"stdout": stdout, "stderr": stderr}
            raise ExternalProcessException("`{}` exited with code {}".format(cmd_str, exit_code), streams)
        return exit_code, stdout, stderr
    else:
        raise ValueError("Invalid exec_local output handling mode: {}".format(mode))
    exit_code = p.wait()

    stdout = to_str(stdout)
    stderr = to_str(stderr)

    if debug:
        log.debug("`{}` exited with code {}\n\tstdout: {}\n\tstderr: {}".format(cmd_str, exit_code, stdout, stderr))

    if raise_nonzero and exit_code != 0:
        streams = {"stdout": stdout, "stderr": stderr}
        raise ExternalProcessException("`{}` exited with code {}".format(cmd_str, exit_code), streams)
    return exit_code, stdout, stderr


def exec_via_ssh(host, *args, no_host_check=False, **kwargs):
    """
    Execute a command on the given host.  If the given host is the current host, then the command is simply executed
    locally instead of via SSH (unless no_host_chceck is specified).

    :param str host: Host on which the given command should be executed
    :param args: Command to be exeuted on the given host
    :param bool no_host_check: Skip check of current host against the given host (default: check)
    :param kwargs: Keyword args to pass doen the chain to :func:`exec_local`
    :return tuple: exit_code, stdout, stderr from the given command (see: :func:`exec_local`)
    """
    if not no_host_check and socket.gethostname() == host:
        return exec_local(*args, **kwargs)

    cmd = " ".join(map(str, args))
    cmd_args = [SSH, host, "-q", "-o", "UserKnownHostsFile=/dev/null", "-o", "StrictHostKeyChecking=no", cmd]
    return exec_local(*cmd_args, **kwargs)


def tee(in_pipe, *out_pipes):
    def _tee(in_pipe, *out_pipes):
        for line in iter(in_pipe.readline, b""):
            for p in out_pipes:
                p.write(to_str(line))
                if (p is sys.stdout) or (p is sys.stderr):
                    p.flush()
        in_pipe.close()
    t = Thread(target=_tee, args=(in_pipe,) + out_pipes)
    t.daemon = True
    t.start()
    return t


def psg(search_term):
    exit_code, stdout, stderr = exec_local("ps", "-efww")
    raw_lines = list(map(str.strip, stdout.splitlines()))
    lines = [line for line in raw_lines[1:] if (search_term in line) and not line.endswith("ps -efww")]
    psg_rx = re.compile("(\S+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(.*)")
    psg_fields = raw_lines[0].split()
    return [dict(zip(psg_fields, psg_rx.match(line).groups())) for line in lines]


class ExternalProcessException(Exception):
    """Exception to be raised when an external process completes with a non-zero exit status"""
