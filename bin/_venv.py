"""
Used by scripts in this directory to activate the

:author: Doug Skrypa
"""

from os import environ


def maybe_activate_venv():
    if not environ.get('VIRTUAL_ENV'):
        from pathlib import Path

        proj_root = Path(__file__).resolve().parents[1]
        for venv_name in ('venv', '.venv'):
            venv_path = proj_root.joinpath(venv_name)
            if venv_path.exists():
                break
        else:
            return

        import platform
        import sys
        from subprocess import call

        on_windows = platform.system().lower() == 'windows'
        bin_path = venv_path.joinpath('Scripts' if on_windows else 'bin')
        environ.update(
            PYTHONHOME='',
            VIRTUAL_ENV=venv_path.as_posix(),
            PATH='{}:{}'.format(bin_path.as_posix(), environ['PATH']),
        )
        cmd = [bin_path.joinpath('python.exe' if on_windows else 'python').as_posix()] + sys.argv
        sys.exit(call(cmd, env=environ))


maybe_activate_venv()
