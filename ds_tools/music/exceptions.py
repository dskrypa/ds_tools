"""
:author: Doug Skrypa
"""

from ..core import cached_property
from ..utils import soupify

__all__ = [
    "MusicException", "InvalidArtistException", "AlbumNotFoundException", "TrackDiscoveryException",
    "AmbiguousEntityException", "WikiEntityParseException", "TrackInfoParseException", "WikiEntityInitException",
    "WikiEntityIdentificationException", "NoTrackListException", "InvalidTrackListException", "WikiTypeError"
]


class MusicException(Exception):
    """Base Exception class for the music package"""


class InvalidArtistException(MusicException):
    pass


class AlbumNotFoundException(MusicException):
    pass


class TrackDiscoveryException(MusicException):
    pass


class WikiEntityParseException(MusicException):
    """Exception to be raised when unable to parse expected content from a WikiEntity's page"""


class NoTrackListException(WikiEntityParseException):
    """Exception to be raised when no track list can be found on an album page"""


class TrackInfoParseException(MusicException):
    """Exception to be raised when unable to parse expected content from a WikiEntity track list item, or track title"""


class WikiEntityInitException(MusicException):
    """Exception to be raised when unable to initialize a WikiEntity"""


class WikiEntityIdentificationException(WikiEntityInitException):
    """Exception to be raised when unable to identify a WikiEntity definitively"""


class InvalidTrackListException(MusicException):
    """Exception to be raised when an invalid track list name was provided"""


class WikiTypeError(TypeError, MusicException):
    """Exception to be raised when an incorrect type was used to initialize a WikiEntity"""
    def __init__(self, url, article, category, cls_cat):
        self.url, self.article, self.category, self.cls_cat = url, article, category, cls_cat

    def __str__(self):
        return "{} is {} {} page (expected: {})".format(self.url, self.article, self.category, self.cls_cat)


class AmbiguousEntityException(MusicException):
    def __init__(self, uri_path, html, obj_type=None):
        self.uri_path = uri_path
        self.html = html
        self.obj_type = obj_type or "Page"

    @cached_property
    def alternative(self):
        alts = self.alternatives
        return alts[0] if len(alts) == 1 else None

    @property
    def potential_alternatives(self):
        alts = []
        for func in ("title", "upper"):
            val = getattr(self.uri_path, func)()
            if val != self.uri_path:
                alts.append(val)
        return alts

    @cached_property
    def alternatives(self):
        soup = soupify(self.html)
        try:
            return [soup.find("span", class_="alternative-suggestion").find("a").text]
        except Exception as e:
            pass

        disambig_div = soup.find("div", id="disambig")
        if disambig_div:
            return [
                a.get("href")[6:] if a.get("href") else a.text.strip()
                for li in disambig_div.parent.find("ul")
                for a in li.find_all("a", limit=1)
            ]
        return []

    def __str__(self):
        alts = self.alternatives
        base = "{} {!r} doesn't exist".format(self.obj_type, self.uri_path)
        if len(alts) == 1:
            return "{} - did you mean {!r}?".format(base, alts[0])
        elif alts:
            return "{} - did you mean one of these? {}".format(base, " | ".join(alts))
        else:
            return "{} and no suggestions could be found.".format(base)
