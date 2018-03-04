#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Connection cleanup

Makes sure that all sockets opened by these modules are closed.

Scripts should include the following:
::
    from cleanup import cleanup

    ...

    if __name__ == "__main__":
        try:
            main()
        except KeyboardInterrupt as e:
            print()
        finally:
            cleanup()

:author: Doug Skrypa
"""

from contextlib import suppress

from .http import http_cleanup

__all__ = ["cleanup"]


def cleanup():
    for cleanup_func in (http_cleanup,):
        with suppress(Exception):
            cleanup_func()
