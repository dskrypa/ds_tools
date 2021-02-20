"""
Exceptions for VCP errors.

:author: Doug Skrypa
"""


class VCPError(Exception):
    """Base VCP exception"""


class VCPPermissionError(VCPError):
    """Error due to insufficient permissions"""


class VCPIOError(VCPError):
    """Error during IO operations"""
