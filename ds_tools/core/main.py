"""
:author: Doug Skrypa
"""

import logging
import sys
from functools import wraps

__all__ = ['wrap_main']
log = logging.getLogger(__name__)


def wrap_main(main):
    """
    Handle quirks related to the inability to use ``signal.signal(signal.SIGPIPE, signal.SIG_DFL)`` in Windows, and
    standardize the handling of KeyboardInterrupt and logging of stack traces/errors on exit with ``sys.exit(1)``.

    :param main: The main function of a program
    :return: The main function, wrapped with exception handlers for common things that need to be handled at exit
    """
    @wraps(main)
    def run_main(*args, **kwargs):
        try:
            try:
                main(*args, **kwargs)
            except OSError as e:
                import platform
                if platform.system().lower() == 'windows' and e.errno == 22:
                    # When using |head, the pipe will be closed when head is done, but Python will still think that it
                    # is open - checking whether sys.stdout is writable or closed doesn't work, so triggering the
                    # error again seems to be the most reliable way to detect this (hopefully) without false positives
                    try:
                        sys.stdout.write('\n')
                        sys.stdout.flush()
                    except OSError:
                        pass
                    else:
                        raise   # If it wasn't the expected error, let the main Exception handler below handle it
                else:
                    raise
        except KeyboardInterrupt:
            print()
        except BrokenPipeError:
            pass
        except Exception as e:
            import traceback
            if _logger_has_non_null_handlers(log):
                log.log(19, traceback.format_exc())     # hide tb since exc may be expected unless output is --verbose
                log.error(e)
            else:               # If logging wasn't configured, or the error occurred before logging could be configured
                print(traceback.format_exc(), file=sys.stderr)
            sys.exit(1)
        finally:
            """
            Prevent the following when piping output to utilities such as ``| head``:
                Exception ignored in: <_io.TextIOWrapper name='<stdout>' mode='w' encoding='utf-8'>
                OSError: [Errno 22] Invalid argument
            """
            try:
                sys.stdout.close()
            except Exception:
                pass
    return run_main


def _logger_has_non_null_handlers(logger):
    # Based on logging.Logger.hasHandlers(), but checks that they are not all NullHandlers
    # Copied from ds_tools.logging to prevent circular dependency
    c = logger
    rv = False
    while c:
        if c.handlers and not all(isinstance(h, logging.NullHandler) for h in c.handlers):
            rv = True
            break
        if not c.propagate:
            break
        else:
            c = c.parent
    return rv
