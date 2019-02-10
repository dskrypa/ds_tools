#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
:author: Doug Skrypa
"""

from ..utils import soupify, cached_property

__all__ = ["InvalidArtistException", "AlbumNotFoundException", "TrackDiscoveryException", "AmbiguousEntityException"]


class InvalidArtistException(Exception):
    pass


class AlbumNotFoundException(Exception):
    pass


class TrackDiscoveryException(Exception):
    pass


class AmbiguousEntityException(Exception):
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
