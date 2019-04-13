"""
:author: Doug Skrypa
"""

__all__ = ['MusicException', 'NoAlbumFoundException', 'NoArtistsFoundException', 'TrackDiscoveryException']


class MusicException(Exception):
    """Base Exception class for the music package"""


class TrackDiscoveryException(MusicException):
    pass


class NoArtistsFoundException(MusicException):
    """Exception to be raised when no artist could be found for a given album/track"""


class NoAlbumFoundException(MusicException):
    """Exception to be raised when an album cannot be found for a given album/track"""
