"""
:author: Doug Skrypa
"""

import os
import logging
import platform
from getpass import getuser

__all__ = ['validate_or_make_dir', 'get_user_cache_dir']
log = logging.getLogger(__name__)

ON_WINDOWS = platform.system().lower() == 'windows'


def validate_or_make_dir(dir_path, permissions=None, suppress_perm_change_exc=True):
    """
    Validate that the given path exists and is a directory.  If it does not exist, then create it and any intermediate
    directories.

    Example value for permissions: 0o1777

    :param str dir_path: The path of a directory that exists or should be created if it doesn't
    :param int permissions: Permissions to set on the directory if it needs to be created (octal notation is suggested)
    :param bool suppress_perm_change_exc: Suppress an OSError if the permission change is unsuccessful (default: suppress/True)
    :return str: The path
    """
    if os.path.exists(dir_path):
        if not os.path.isdir(dir_path):
            raise ValueError('Invalid path - not a directory: {}'.format(dir_path))
    else:
        os.makedirs(dir_path)
        if permissions is not None:
            try:
                os.chmod(dir_path, permissions)
            except OSError as e:
                log.error('Error changing permissions of path {!r} to 0o{:o}: {}'.format(dir_path, permissions, e))
                if not suppress_perm_change_exc:
                    raise e
    return dir_path


def get_user_cache_dir(subdir=None, permissions=None):
    cache_dir = os.path.join('C:/var/tmp' if ON_WINDOWS else '/var/tmp', getuser(), 'ds_tools_cache')
    if subdir:
        cache_dir = os.path.join(cache_dir, subdir)
    validate_or_make_dir(cache_dir, permissions=permissions)
    return cache_dir
