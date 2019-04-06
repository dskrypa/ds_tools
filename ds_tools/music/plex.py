"""
Module for syncing Plex ratings with ratings stored in ID3 tags

:author: Doug Skrypa
"""

import logging
from getpass import getpass
from pathlib import Path

from plexapi.myplex import MyPlexAccount
from plexapi.server import PlexServer
from requests import Session
from urllib3 import disable_warnings as disable_urllib3_warnings

from ..core import InputValidationException, cached_property
from .files import SongFile

__all__ = ['LocalPlexServer']
log = logging.getLogger(__name__)

disable_urllib3_warnings()


class LocalPlexServer:
    def __init__(self, url=None, user=None, server_path_root=None, cache_dir='~/.plex'):
        self._cache = Path(cache_dir).expanduser().resolve()
        if not self._cache.exists():
            self._cache.mkdir(parents=True)

        if not url:
            url_path = self._cache.joinpath('server_url.txt')
            if url_path.exists():
                url = url_path.open('r').read().strip()
            if not url:
                raise ValueError('A server URL must be provided or be in {}'.format(url_path.as_posix()))
        self.url = url
        self.user = user
        if not server_path_root:
            root_path = self._cache.joinpath('server_path_root.txt')
            if root_path.exists():
                server_path_root = root_path.open('r').read().strip()
            if not server_path_root:
                raise ValueError('A server root path must be provided or be in {}'.format(root_path.as_posix()))
        self.server_root = Path(server_path_root)

    @cached_property
    def _token(self):
        token_path = self._cache.joinpath('token.txt')
        if token_path.exists():
            log.debug('Reading Plex token from {}'.format(token_path))
            with token_path.open('r') as f:
                return f.read()
        else:
            if self.user is None:
                try:
                    self.user = input('Please enter your Plex username:').strip()
                except EOFError as e:
                    raise InputValidationException('Unable to read stdin (this is often caused by piped input)') from e

            account = MyPlexAccount(self.user, getpass())
            with token_path.open('w') as f:
                f.write(account._token)
            return account._token

    @cached_property
    def _sesssion(self):
        session = Session()
        session.verify = False
        return PlexServer(self.url, self._token, session=session)

    @cached_property
    def music(self):
        return self._sesssion.library.section('Music')

    def get_tracks(self, **kwargs):
        return self.music.fetchItems('/library/sections/1/all?type=10', **kwargs)

    def get_track(self, **kwargs):
        return self.music.fetchItem('/library/sections/1/all?type=10', **kwargs)

    def find_songs_by_rating_gte(self, rating, **kwargs):
        """
        :param int rating: Song rating on a scale of 0-10
        :return list: List of :class:`plexapi.audio.Track` objects
        """
        return self.get_tracks(userRating__gte=rating, **kwargs)

    def find_song(self, path):
        return self.get_track(media__part__file=path)

    def sync_ratings_to_files(self, path_filter=None, dry_run=False):
        """
        Sync the song ratings from this Plex server to the files

        :param str path_filter: String that file paths must contain to be sync'd
        :param bool dry_run: Dry run - print the actions that would be taken instead of taking them
        """
        prefix = '[DRY RUN] Would update' if dry_run else 'Updating'
        kwargs = {'media__part__file__icontains': path_filter} if path_filter else {}
        for track in self.find_songs_by_rating_gte(1, **kwargs):
            file = SongFile.for_plex_track(track)
            file_stars = file.star_rating_10
            plex_stars = track.userRating
            if file_stars == plex_stars:
                log.log(9, 'Rating is already correct for {}'.format(file))
            else:
                log.info('{} rating from {} to {} for {}'.format(prefix, file_stars, plex_stars, file))
                if not dry_run:
                    file.star_rating_10 = plex_stars

    def sync_ratings_from_files(self, path_filter=None, dry_run=False):
        """
        Sync the song ratings on this Plex server with the ratings in the files

        :param str path_filter: String that file paths must contain to be sync'd
        :param bool dry_run: Dry run - print the actions that would be taken instead of taking them
        """
        prefix = '[DRY RUN] Would update' if dry_run else 'Updating'
        kwargs = {'media__part__file__icontains': path_filter} if path_filter else {}
        for track in self.get_tracks(**kwargs):
            file = SongFile.for_plex_track(track)
            file_stars = file.star_rating_10
            if file_stars is not None:
                plex_stars = track.userRating
                if file_stars == plex_stars:
                    log.log(9, 'Rating is already correct for {}'.format(file))
                else:
                    log.info('{} rating from {} to {} for {}'.format(prefix, plex_stars, file_stars, file))
                    if not dry_run:
                        track.edit(**{'userRating.value': file_stars})


def print_song_info(songs):
    for song in songs:
        print('{} - {} - {} - {}'.format(stars(song.userRating), song.artist().title, song.album().title, song.title))


def stars(rating, out_of=10, num_stars=5):
    if out_of < 1:
        raise ValueError('out_of must be > 0')
    filled = int(num_stars * rating / out_of)
    empty = num_stars - filled
    # return '\u2605' * filled + '\u2606' * empty
    return '*' * filled + ' ' * empty


if __name__ == '__main__':
    # from ds_tools.logging import LogManager
    from .patches import apply_mutagen_patches
    apply_mutagen_patches()
    # lm = LogManager.create_default_logger(2, log_path=None, entry_fmt='%(asctime)s %(name)s %(message)s')
