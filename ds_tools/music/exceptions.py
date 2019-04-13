"""
:author: Doug Skrypa
"""

__all__ = ['MusicException', 'NoArtistsFoundException', 'TrackDiscoveryException']


class MusicException(Exception):
    """Base Exception class for the music package"""


class TrackDiscoveryException(MusicException):
    pass


class NoArtistsFoundException(MusicException):
    """Exception to be raised when no artist could be found for a given album/track"""
