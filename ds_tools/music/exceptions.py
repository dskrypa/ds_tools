"""
:author: Doug Skrypa
"""

__all__ = ['MusicException', 'TrackDiscoveryException']


class MusicException(Exception):
    """Base Exception class for the music package"""


class TrackDiscoveryException(MusicException):
    pass
