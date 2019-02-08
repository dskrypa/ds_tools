#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
:author: Doug Skrypa
"""

from ..utils import soupify, cached_property

__all__ = ["InvalidArtistException", "AlbumNotFoundException", "TrackDiscoveryException", "AmbiguousArtistException"]


class InvalidArtistException(Exception):
    pass


class AlbumNotFoundException(Exception):
    pass


class TrackDiscoveryException(Exception):
    pass


class AmbiguousArtistException(Exception):
    def __init__(self, artist, html):
        self.artist = artist
        self.html = html

    @cached_property
    def alternative(self):
        alts = self.alternatives
        return alts[0] if len(alts) == 1 else None

    @cached_property
    def alternatives(self):
        soup = soupify(self.html)
        try:
            return [soup.find("span", class_="alternative-suggestion").find("a").text]
        except Exception as e:
            pass

        disambig_div = soup.find("div", id="disambig")
        if disambig_div:
            return [li.find("a").get("href")[6:] for li in disambig_div.parent.find("ul")]
        return []

    def __str__(self):
        alts = self.alternatives
        if len(alts) == 1:
            return "Artist {!r} doesn't exist - did you mean {!r}?".format(self.artist, alts[0])
        elif alts:
            return "Artist {!r} doesn't exist - did you mean one of these? {}".format(self.artist, " | ".join(alts))
        else:
            return "Artist {!r} doesn't exist and no suggestions could be found."
