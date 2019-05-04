"""
:author: Doug Skrypa
"""

__all__ = [
    'MusicException', 'NoAlbumFoundException', 'NoArtistsFoundException', 'TrackDiscoveryException',
    'NoMatchFoundException', 'NoTrackFoundException', 'NameFormatError'
]


class MusicException(Exception):
    """Base Exception class for the music package"""


class TrackDiscoveryException(MusicException):
    pass


class NoMatchFoundException(MusicException):
    """Exception to be raised when no Wiki match could be found for a given file"""


class NoArtistsFoundException(NoMatchFoundException):
    """Exception to be raised when no artist could be found for a given album/track"""


class NoAlbumFoundException(NoMatchFoundException):
    """Exception to be raised when an album cannot be found for a given album/track"""


class NoTrackFoundException(NoMatchFoundException):
    """Exception to be raised when a track cannot be matched to a track in a wiki"""


class NameFormatError(MusicException, ValueError):
    """Exception to be raised when a name is encountered that doesn't match any expected format"""
