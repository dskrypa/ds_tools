#!/usr/bin/env python3

import grp  # noqa
import logging
import pwd  # noqa
import sys
from argparse import ArgumentParser
from pathlib import Path
from shutil import unpack_archive
from subprocess import check_call, check_output, SubprocessError
from tempfile import TemporaryDirectory

sys.path.insert(0, Path(__file__).resolve().parents[1].as_posix())
from ds_tools.installer.apps.grafana import Promtail

# GH_OWNER = 'grafana'
# GH_REPO = 'loki'
PROGRAM = 'promtail'
# GH_API_URL = f'https://api.github.com/repos/{GH_OWNER}/{GH_REPO}/releases'
# ZIP_NAME = f'{PROGRAM}-freebsd-amd64.zip'
# DL_URL_FMT = f'https://github.com/{GH_OWNER}/{GH_REPO}/releases/download/{{}}/{ZIP_NAME}'


def main():
    parser = ArgumentParser(description=f'Install {PROGRAM.title()} in FreeBSD')
    parser.add_argument('--name', '-n', default=PROGRAM, help='The name of the service to create')
    parser.add_argument('--user', '-u', default=PROGRAM, help=f'The user that should be configured to run {PROGRAM}')
    parser.add_argument('--group', '-g', default=PROGRAM, help='The group that the specified user should be added to')
    parser.add_argument('--install_path', '-i', help=f'The path to install the {PROGRAM} binary')
    parser.add_argument('--config_path', '-c', help=f'The path to install the {PROGRAM} config file')
    parser.add_argument('--version', '-V', help=f'The version of {PROGRAM} to install (default: latest)')

    cfg_group = parser.add_argument_group('Promtail Config')
    cfg_group.add_argument('--http_port', '-p', type=int, default=9080, help='Promtail server listen port')
    cfg_group.add_argument('--grpc_port', type=int, default=0, help='Promtail GRPC listen port')
    cfg_group.add_argument('--pos_path', default='/tmp/positions.yaml', help='Path to store log tail positions')
    cfg_group.add_argument('--loki_scheme', default='http', choices=('http', 'https'), help='Scheme for Loki push client')
    cfg_group.add_argument('--loki_netloc', '-L', default='localhost:3100', help='Host and port for Loki push client')

    log_group = parser.add_argument_group('Log Scrape Config')
    log_group.add_argument('--logs', metavar='JOB:PATH_PATTERN', nargs='+', help='One or more paths to monitor')

    parser.add_argument('--verbose', '-v', action='count', default=0, help='Increase logging verbosity (can specify multiple times)')
    args = parser.parse_args()

    log_fmt = '%(asctime)s %(levelname)s %(name)s %(lineno)d %(message)s' if args.verbose > 1 else '%(message)s'
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format=log_fmt)

    promtail = Promtail(
        name=args.name,
        user=args.user,
        group=args.group,
        bin_path=args.install_path,
        http_port=args.http_port,
        grpc_port=args.grpc_port,
        pos_path=args.pos_path,
        loki_scheme=args.loki_scheme,
        loki_netloc=args.loki_netloc,
        config_path=args.config_path,
        logs=args.logs,
    )
    promtail.download_and_install()

    # rc_d_dir = Path('/usr/local/etc/rc.d')
    # if not rc_d_dir.exists():
    #     raise RuntimeError(f'Could not find {rc_d_dir.as_posix()} - {Path(__file__).name} only supports setup via rc')
    #
    # rc_d_dir_stat = rc_d_dir.stat()
    # if rc_d_dir_stat.st_uid != os.getuid() or rc_d_dir_stat.st_gid != os.getgid():
    #     raise RuntimeError(f'You must run `sudo {Path(__file__).name}` to proceed')
    #
    # ensure_user_exists(args.user)
    # ensure_user_is_in_group(args.user, args.group)
    # download_and_install(args.install_path, args.version)
    # create_config_yaml(
    #     args.config_path, args.http_port, args.grpc_port, args.pos_path, args.loki_scheme, args.loki_netloc
    # )
    # create_rcd_script(args.name, args.install_path, args.config_path, args.user, args.group)
    # enable_and_start(args.name)


# region User/Group Creation


def ensure_user_exists(user: str):
    try:
        pwd_user = pwd.getpwnam(user)
    except KeyError:
        pass
    else:
        print(f'User={user!r} already exists')
        return

    print(f'Creating user={user!r}')
    check_call(['pw', 'user', 'add', user])


def ensure_user_is_in_group(user: str, group: str):
    user_struct = pwd.getpwnam(user)
    gid = user_struct.pw_gid
    group_struct = grp.getgrgid(gid)
    if group_struct.gr_name == group:
        print(f'User={user!r} is already in group={group!r}')
        return

    try:
        group_struct = grp.getgrnam(group)
    except KeyError:
        print(f'Creating group={group!r}')
        check_call(['pw', 'group', 'add', group])
        group_struct = grp.getgrnam(group)

    if user not in group_struct.gr_mem:
        print(f'Adding user={user!r} to group={group!r}')
        check_call(['pw', 'user', 'mod', user, '-G', group])


# endregion

# region Service Creation

def create_rcd_script(name: str, install_path: str, config_path: str, user: str, group: str):
    script_path = Path('/usr/local/etc/rc.d', name)
    script = fr"""#!/bin/sh

# PROVIDE: {name}
# REQUIRE: LOGIN
# KEYWORD: shutdown

# Add the following lines to /etc/rc.conf to enable {name}
# {name}_enable="YES"
#
# {name}_enable (bool):
#     Set it to YES to enable {name}
#     Set to NO by default
# {name}_user (string):
#     Set user that {name} will run under
#     Default is "{user}"
# {name}_group (string):
#     Set group that own {name} files
#     Default is "{group}"
# {name}_config (string)
#     Set full path to config file
#     Default is "{config_path}"
# {name}_args (string)
#     Set additional command line arguments
#     Default is ""

. /etc/rc.subr

name={name}
rcvar={name}_enable

load_rc_config $name

: ${{{name}_enable:="NO"}}
: ${{{name}_user:="{user}"}}
: ${{{name}_group:="{group}"}}
: ${{{name}_config:="{config_path}"}}

pidfile="/var/run/${{name}}/${{name}}.pid"
required_files="${{{name}_config}}"

procname="{install_path}"
command="/usr/sbin/daemon"
command_args="-f -T ${{name}} -p ${{pidfile}} -t ${{name}} \
            /usr/bin/env ${{{name}_env}} \
            ${{procname}} -config.file=${{{name}_config}} ${{{name}_args}}"

start_precmd="{name}_start_precmd"

{name}_start_precmd() {{
    if [ ! -d "/var/run/${{name}}" ]; then
        install -d -m 0750 -o ${{{name}_user}} -g ${{{name}_group}} "/var/run/${{name}}"
    fi
}}

run_rc_command "$1"
"""
    if script_path.exists():
        raise RuntimeError(f'Service script {script_path.as_posix()} already exists')

    print(f'Creating {script_path.as_posix()}')
    with script_path.open('w', encoding='utf-8') as f:
        f.write(script)
    script_path.chmod(0o755)


def enable_and_start(name: str):
    print(f'Enabling service={name}')
    check_call(['sysrc', f'{name}_enable=YES'])
    print(f'Starting service={name}')
    check_call(['service', name, 'start'])

# endregion


def create_config_yaml(path: str, http_port: int, grpc_port: int, pos_path: str, scheme: str, netloc: str):
    config = f"""
server:
  http_listen_port: {http_port}
  grpc_listen_port: {grpc_port}
positions:
  filename: {pos_path}
clients:
  - url: {scheme}://{netloc}/loki/api/v1/push
#scrape_configs:
#- job_name: example
#  static_configs:
#  - labels: {{job: example, __path__: /var/log/*log}}
""".lstrip()
    path = Path(path)
    if not path.parent.exists():
        path.parent.mkdir(parents=True)

    print(f'Writing config to {path}')
    path.write_text(config, encoding='utf-8')
    path.chmod(0o644)


# region Download & Install Binaries


def download_and_install(path: str, version: str = None):
    if version is None:
        version, mode = find_latest_version()
    else:
        try:
            import requests
        except ImportError:
            mode = 'curl'
        else:
            mode = 'requests'

    dest_path = Path(path)
    if dest_path.exists():
        current = get_current_version(dest_path.as_posix())
        if current and version in (current, f'v{current}'):
            print(f'Skipping download - version={version!r} is already installed')
            return

    _download_and_install(version, mode, path)


def _download_and_install(version: str, mode: str, path: str):
    with TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        zip_path = tmp_path.joinpath(ZIP_NAME)  # type: Path
        print(f'Downloading {PROGRAM} version={version!r}')
        if mode == 'requests':
            _download_via_requests(zip_path, version)
        elif mode == 'curl':
            try:
                _download_via_curl(zip_path, version)
            except SubprocessError:
                _missing_dependencies()
        else:
            raise RuntimeError(f'Unexpected download mode={mode!r}')

        unpack_archive(zip_path.as_posix(), tmp_dir)
        print(f'Unpacking {zip_path.name}')
        tmp_bin_path = next((p for p in tmp_path.iterdir() if p != zip_path))  # type: Path

        dest_path = Path(path)
        if dest_path.exists():
            print(f'Removing old {dest_path.as_posix()}')
            dest_path.unlink()

        tmp_bin_path.rename(dest_path)
        print(f'Created {dest_path.as_posix()}')
        dest_path.chmod(0o755)


def _download_via_requests(zip_path: Path, version: str):
    import requests

    with zip_path.open('wb') as f:
        resp = requests.get(DL_URL_FMT.format(version))
        f.write(resp.content)


def _download_via_curl(zip_path: Path, version: str):
    check_call(['curl', '--location', DL_URL_FMT.format(version), '-o', zip_path.as_posix()])


def get_current_version(install_path: str):
    try:
        stdout = check_output([install_path, '-version'], text=True)  # type: str
    except (SubprocessError, OSError):
        return None
    else:
        return stdout.splitlines()[0].split('(', 1)[0].partition('version')[-1].strip()


def _missing_dependencies():
    import platform

    py_ver = ''.join(platform.python_version_tuple()[:2])
    error_msg = (
        f'Unable to install {PROGRAM} due to missing install time dependencies.\n'
        'One of the following is required:\n'
        f'  - `pip install requests` (you may need to run `pkg install py{py_ver}-pip` first)\n'
        '  - `pkg install curl`\n'
    )
    raise RuntimeError(error_msg)


def find_latest_version():
    try:
        return _find_latest_via_requests()
    except ImportError:
        pass

    try:
        return _find_latest_via_curl()
    except SubprocessError:
        pass

    _missing_dependencies()


def _find_latest_via_requests():
    import requests

    releases = requests.get(GH_API_URL).json()
    return releases[0]['tag_name'], 'requests'


def _find_latest_via_curl():
    import json

    stdout = check_output(['curl', GH_API_URL])
    releases = json.loads(stdout)
    return releases[0]['tag_name'], 'curl'


# endregion


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print()
