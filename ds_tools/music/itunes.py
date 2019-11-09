"""
Module for syncing iTunes ratings with ratings stored in ID3 tags

:author: Doug Skrypa
"""

import logging
import re
from collections import OrderedDict
from html import unescape
from pathlib import Path
from urllib.parse import unquote

from .files import SongFile

__all__ = ['ItunesLibrary']
log = logging.getLogger(__name__)


class ItunesLibrary:
    def __init__(self, lib_path=None):
        self.lib_path = Path(lib_path if lib_path else '~/Music/iTunes/Library.xml').expanduser().resolve()
        with self.lib_path.open('r', encoding='utf-8') as f:
            self._content = f.read()

        prefix = []
        tracks = OrderedDict()
        suffix = []

        kv_rx = re.compile(r'\t\t\t<key>(.*)</key>(.*)')
        beginning = True
        end = False
        last = None
        for line in self._content.splitlines():
            if beginning:
                if line.startswith('\t\t<key>'):
                    beginning = False
                    tracks[line] = ([], OrderedDict())
                    last = line
                else:
                    prefix.append(line)
            elif end:
                suffix.append(line)
            elif line.startswith('\t</dict>'):
                end = True
                suffix.append(line)
            else:
                if line.startswith('\t\t<key>'):
                    tracks[line] = ([], OrderedDict())
                    last = line
                elif line.startswith(('\t\t<dict>', '\t\t</dict>')):
                    tracks[last][0].append(line)
                else:
                    tracks[last][0].append(line)
                    try:
                        key, val = kv_rx.match(line).groups()
                    except AttributeError as e:
                        log.error('Error on line: {!r}'.format(line))
                        raise e

                    tracks[last][1][key] = (len(tracks[last][0]) - 1, val)

        self.prefix = prefix
        self.tracks = tracks
        self.suffix = suffix

    def sync_ratings_from_files(self, dry_run=False):
        """
        Sync the song ratings on this iTunes library with the ratings in the files

        :param bool dry_run: Dry run - print the actions that would be taken instead of taking them
        """
        prefix = '[DRY RUN] Would update' if dry_run else 'Updating'

        val_rx = re.compile(r'<([^>]+)>(.*)</\1>')
        rating_fmt = '\t\t\t<key>Rating</key><integer>{}</integer>'

        already_correct = 0
        changed = 0
        for track_key, track in self.tracks.items():
            track_dict = track[1]
            loc = track_dict['Location'][1]
            song_path = unescape(unquote(val_rx.match(loc).group(2)[17:]))
            file = SongFile(song_path)
            try:
                file_stars = file.star_rating_10
            except Exception as e:
                log.error('Error on {}: {}'.format(song_path, e), extra={'color': 'red'})
            else:
                if file_stars is not None:
                    itunes_rating = track_dict.get('Rating')
                    if itunes_rating is not None:
                        val = val_rx.match(itunes_rating[1]).group(2)
                        itunes_stars = int(val) / 10
                    else:
                        itunes_stars = None

                    if file_stars == itunes_stars:
                        already_correct += 1
                        log.log(7, 'Rating is already correct for {}'.format(file))
                    else:
                        log.log(19, '{} rating from {} to {} for {}'.format(prefix, itunes_stars, file_stars, file))
                        if not dry_run:
                            changed += 1
                            if itunes_rating is not None:
                                idx = itunes_rating[0]
                                track[0][idx] = rating_fmt.format(file_stars * 10)
                            else:
                                idx = track_dict['Sample Rate'][0] + 1
                                track[0].insert(idx, rating_fmt.format(file_stars * 10))

        if already_correct:
            log.info('Track ratings were already correct for {:,d} tracks'.format(already_correct))
        if changed:
            log.info('Track ratings were updated for {:,d} tracks'.format(changed))

        if changed and not dry_run:
            track_lines = []
            for track_key, track in self.tracks.items():
                track_lines.append(track_key)
                track_lines.extend(track[0])
            new_content = self.prefix + track_lines + self.suffix
            self.lib_path.rename(self.lib_path.with_name('iTunes Music Library.bkp'))
            with self.lib_path.open('w', encoding='utf-8') as f:
                for line in new_content:
                    f.write(line + '\n')
