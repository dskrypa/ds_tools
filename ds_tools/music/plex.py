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
            log.debug('')
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

    def find_songs_by_rating_gte(self, rating):
        """
        :param int rating: Song rating on a scale of 0-10
        :return list: List of :class:`plexapi.audio.Track` objects
        """
        return self.music.fetchItems('/library/sections/1/all?type=10', userRating__gte=rating)

    def find_song(self, path):
        return self.music.fetchItem('/library/sections/1/all?type=10', media__part__file=path)


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
    from ds_tools.logging import LogManager
    lm = LogManager.create_default_logger(2, log_path=None, entry_fmt='%(asctime)s %(name)s %(message)s')
