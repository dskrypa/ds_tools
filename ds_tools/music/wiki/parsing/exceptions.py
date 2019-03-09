"""
:author: Doug Skrypa
"""

from ..exceptions import MusicWikiException

__all__ = ['NoTrackListException', 'TrackInfoParseException', 'WikiEntityParseException']


class WikiEntityParseException(MusicWikiException):
    """Exception to be raised when unable to parse expected content from a WikiEntity's page"""


class NoTrackListException(WikiEntityParseException):
    """Exception to be raised when no track list can be found on an album page"""


class TrackInfoParseException(MusicWikiException):
    """Exception to be raised when unable to parse expected content from a WikiEntity track list item, or track title"""
