"""
Exceptions for media processing utilities.

:author: Doug Skrypa
"""


class FfmpegError(Exception):
    """Base exception for errors related to using ffmpeg"""

    def __init__(self, command: list[str], message: str):
        self.command = command
        self.message = message

    def __str__(self) -> str:
        return f'Error running {self.command[0]}: {self.message}'
