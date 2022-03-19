"""
Download helpers

:author: Doug Skrypa
"""

import json
from pathlib import Path
from subprocess import check_call, check_output, SubprocessError

__all__ = ['get_json', 'save_file']


def _download_func(req_func, curl_func):
    def download_func(url: str, curl_args=(), *args, **kwargs):
        try:
            return req_func(url, *args, **kwargs)
        except ImportError:
            pass
        try:
            return curl_func(url, curl_args, *args, **kwargs)
        except SubprocessError:
            pass
        missing_dependencies(url)

    return download_func


# region Get Json

def _get_json_via_requests(url: str):
    import requests

    with requests.Session() as session:
        return session.get(url).json()


def _get_json_via_curl(url: str, args=()):
    stdout = check_output(['curl', url, *args])
    return json.loads(stdout)


get_json = _download_func(_get_json_via_requests, _get_json_via_curl)

# endregion


# region Get File

def _save_file_via_requests(url: str, save_path: Path):
    import requests

    with save_path.open('wb') as f, requests.Session() as session:
        resp = session.get(url)
        f.write(resp.content)


def _save_file_via_curl(url: str, save_path: Path, args=()):
    check_call(['curl', url, '-o', save_path.as_posix(), *args])


save_file = _download_func(_save_file_via_requests, _save_file_via_curl)

# endregion


def missing_dependencies(url: str):
    import platform
    from distutils.spawn import find_executable

    msg_parts = [
        f'Unable to download {url} due to missing install time dependencies.',
        'One of the following is required:',
        '  - `pkg install curl`'
    ]
    if find_executable('pip') is None:
        if platform.uname().system.lower() == 'freebsd':
            py_ver = ''.join(platform.python_version_tuple()[:2])
            cmd = f'pkg install py{py_ver}-pip'
        else:
            cmd = 'apt install python3-pip'
        extra = f' (you may need to run `{cmd}` first)'
    else:
        extra = ''

    msg_parts.append(f'  - `pip install requests`{extra}')
    raise RuntimeError('\n'.join(msg_parts))
