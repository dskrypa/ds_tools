#!/usr/bin/env python3

import json
import logging
import os
import re
import sys
import unittest
from collections import Counter

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)
from ds_tools.logging import LogManager
from ds_tools.music.wiki import Artist, Album, TitleParser

log = logging.getLogger("ds_tools.{}".format(__name__))


class MusicTester(unittest.TestCase):
    def test_iter_songs(self):
        print("", file=sys.stderr)  # stderr so a newline will be printed even when grepping
        with open(os.path.join(BASE_DIR, "music/artist_dir_to_artist.json"), "r", encoding="utf-8") as f:
            artists = json.load(f)

        for artist in sorted(artists.keys()):
            for album in Artist(artist):
                i = 0
                for song in album:
                    i += 1
                    self.assertTrue(bool(song.title), "Song {} from {} has no title".format(song, album))

                # log.info("{}:  {}".format(album, album.expected_dirname))
                log.info("{}".format(album.expected_rel_path))
                if album.is_repkg_double_page:
                    if album.is_repackage:
                        orig = album.repackage_of
                        self.assertTrue(orig is not None, "{} is a repackage, but its original album is unknown".format(album))
                        self.assertLess(len(orig.tracks) - len(album.tracks), 3, "{} is a repackage of {}, but it has significantly fewer songs".format(album, orig))

                    # log.info("{}:  {}".format(album, album.length_str))

                    # for song in album:
                    #     log.info("    {}".format(song))

                    # if song.length == "-1:00":
                        # log.warning("Invalid length found in {} on page {}".format(song, song.album._uri_path), extra={"red": True})
                        # log.warning("Invalid length found in {} on page {}".format(song, song.album._uri_path))

                # print("{}: {}".format(album, i))
                    # print("\t", song)
        # self.assertTrue(True, "If this is not reached, then an exception was raised")

        # with open("/var/tmp/raw_song_names.txt", "w", encoding="utf-8") as f:
        #     f.write("\n".join(sorted(Album.raw_track_names)) + "\n")
        #
        # with open("/var/tmp/raw_album_names.txt", "w", encoding="utf-8") as f:
        #     f.write("\n".join(sorted(Artist.raw_album_names)) + "\n")

    def test_title_parser(self):
        print("", file=sys.stderr)  # stderr so a newline will be printed even when grepping
        p = TitleParser()
        with open("/var/tmp/raw_song_names.txt", "r", encoding="utf-8") as f:
            song_names = f.read().splitlines()

        for i, song in enumerate(song_names):
            parsed = p.parse(song)
            # print("{:>5,d} {!r} => {}".format(i, song, p.parse(song)))

    def _test_song_regexes(self):
        print()
        with open("/var/tmp/raw_song_names.txt", "r", encoding="utf-8") as f:
            song_names = f.read().splitlines()

        not_matched = []
        matches = Counter()
        patterns = [
            # re.compile("\"([^\"]+)\"\s+-\s+(\d+:\d{2})\s+\((.*)\)"),
            # re.compile("\"([^\"]+)\"\s+\((.*)\)-\s+(\d+:\d{2})"),
            re.compile("^[\"“]([^\"]+)[\"“]\s*[-–]?\s*(\d+:\d{2})$"),

            re.compile("^[\"“]([^\"]+)[\"“]\s*[-–]?\s*(\d+:\d{2})\s*\((.*)\)$"),

            re.compile("^[\"“]([^\"]+)[\"“]\s*\((.*)\)\"?\s*[-–]?\s*(\d+:\d{2})$"),

            re.compile("^[^\"“](.+)\(([^)]+)\)\s+[-–]\s+(\d+:\d{2})$"),

            re.compile("^[\"“]([^\"]+)[\"“]$"),

            re.compile("^[\"“]([^\"]+)[\"“]\s+\((.*)\)$"),
        ]
        # “frozen“– 1

        for song in song_names:
            song_matches = 0
            for i, pat in enumerate(patterns):
                if pat.match(song):
                    matches[str(i)] += 1
                    song_matches += 1
            if song_matches > 1:
                matches["multi"] += 1
            elif song_matches == 0:
                not_matched.append(song)

        song_count = len(song_names)
        for i, count in sorted(matches.items()):
            print("{}: {} / {}".format(i, count, song_count))

        print("{}: {} / {}".format("total", song_count - len(not_matched), song_count))

        # print()
        # print()
        # for song in not_matched:
        #     print(song)


if __name__ == "__main__":
    try:
        LogManager.create_default_logger(2, log_path=None)
        unittest.main(warnings="ignore", verbosity=2, exit=False)
    except KeyboardInterrupt:
        print()

