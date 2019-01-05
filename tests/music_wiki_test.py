#!/usr/bin/env python3

import json
import logging
import os
import sys
import unittest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)
from ds_tools.logging import LogManager
from ds_tools.music.wiki import Artist

log = logging.getLogger("ds_tools.{}".format(__name__))


class MusicTester(unittest.TestCase):
    def test_iter_songs(self):
        with open(os.path.join(BASE_DIR, "music/artist_dir_to_artist.json"), "r", encoding="utf-8") as f:
            artists = json.load(f)

        for artist in sorted(artists.keys()):
            for album in Artist(artist):
                for song in album:
                    self.assertTrue(bool(song.title), "Song {} from {} has no title".format(song, album))
                print(album)    # printing after iterating over songs so that the artist is updated
                    # print("\t", song)
        # self.assertTrue(True, "If this is not reached, then an exception was raised")


if __name__ == "__main__":
    try:
        LogManager.create_default_logger(2, log_path=None)
        unittest.main(warnings="ignore", verbosity=2, exit=False)
    except KeyboardInterrupt:
        print()


