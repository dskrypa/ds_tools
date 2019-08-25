"""
Exceptions used by the ds_tools.core package

:author: Doug Skrypa
"""

import logging

__all__ = ['InputValidationException']
log = logging.getLogger(__name__)


class InputValidationException(Exception):
    """Exception to be raised when input does not pass validation"""
