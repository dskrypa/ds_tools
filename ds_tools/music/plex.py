"""
Module for syncing Plex ratings with ratings stored in ID3 tags

Note on fetchItems:
The kwargs to fetchItem/fetchItems use __ to access nested attributes, but the only nested attributes available are
those that are returned in the items in ``plex._session.query(plex._ekey(search_type))``, not the higher level objects.
Example available attributes::\n
    >>> data = plex._session.query(plex._ekey('album'))
    >>> data[0]
    <Element 'Directory' at 0x000001DF71118EF8>
    >>> data[0].attrib.keys()
    dict_keys(['ratingKey', 'key', 'parentRatingKey', 'type', 'title', 'parentKey', 'parentTitle', 'summary', 'index', 'year', 'thumb', 'parentThumb', 'originallyAvailableAt', 'addedAt', 'updatedAt', 'deepAnalysisVersion'])
    >>> [c for c in data[0]]
    [<Element 'Genre' at 0x000001DF711182C8>]
    >>> {c.tag: c.attrib.keys() for c in data[0]}
    {'Genre': dict_keys(['tag'])}

Example playlist syncs::\n
    >>> plex.sync_playlist('K-Pop 3+ Stars', userRating__gte=6, genre__like='[kj]-?pop')
    2019-06-01 08:53:39 EDT INFO __main__ 178 Creating playlist K-Pop 3+ Stars with 485 tracks
    >>> plex.sync_playlist('K-Pop 4+ Stars', userRating__gte=8, genre__like='[kj]-?pop')
    2019-06-01 08:54:13 EDT INFO __main__ 178 Creating playlist K-Pop 4+ Stars with 257 tracks
    >>> plex.sync_playlist('K-Pop 5 Stars', userRating__gte=10, genre__like='[kj]-?pop')
    2019-06-01 08:54:22 EDT INFO __main__ 178 Creating playlist K-Pop 5 Stars with 78 tracks
    >>> plex.sync_playlist('K-Pop 5 Stars', userRating__gte=10, genre__like='[kj]-?pop')
    2019-06-01 08:54:58 EDT VERBOSE __main__ 196 Playlist K-Pop 5 Stars does not contain any tracks that should be removed
    2019-06-01 08:54:58 EDT VERBOSE __main__ 208 Playlist K-Pop 5 Stars is not missing any tracks
    2019-06-01 08:54:58 EDT INFO __main__ 212 Playlist K-Pop 5 Stars contains 78 tracks and is already in sync with the given criteria

:author: Doug Skrypa
"""

import logging
import re
from getpass import getpass
from pathlib import Path

import plexapi
from plexapi.myplex import MyPlexAccount
from plexapi.playlist import Playlist
from plexapi.server import PlexServer
from plexapi.utils import SEARCHTYPES
from requests import Session
from urllib3 import disable_warnings as disable_urllib3_warnings

from ..core import InputValidationException, cached_property
from .files import SongFile

__all__ = ['LocalPlexServer']
log = logging.getLogger(__name__)

disable_urllib3_warnings()

# add compiled regex pattern search as a fetchItem operator
plexapi.base.OPERATORS['sregex'] = lambda v, pat: pat.search(v)


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
    def _session(self):
        session = Session()
        session.verify = False
        return PlexServer(self.url, self._token, session=session)

    @cached_property
    def music(self):
        return self._session.library.section('Music')

    def _ekey(self, search_type):
        return '/library/sections/1/all?type={}'.format(SEARCHTYPES[search_type])

    def _update_kwargs(self, kwargs):
        """
        Update the kwarg search filters for a fetchItem/fetchItems call using custom search filters.

        Implemented custom filters:
         - genre__like: Plex stores genres at the album level rather than the track level - this will run a search for
           albums where re.search(value, album_genre) returns a match, then add a filter for the intended track search
           so that only tracks that are in the albums with the given genre are returned.

        :param dict kwargs: The kwargs that were passed to :meth:`.get_tracks` or a similar method
        :return dict: Modified kwargs with custom search filters
        """
        genre__like = kwargs.pop('genre__like', None)
        if genre__like is not None:
            albums = self.music.fetchItems(self._ekey('album'), genre__tag__sregex=re.compile(genre__like, re.I))
            album_keys = {a.key for a in albums}
            log.debug('Replacing \'genre__like\' with parentKey__in={}'.format(album_keys))
            kwargs['parentKey__in'] = album_keys
        artist = kwargs.pop('artist', None)
        if artist is not None:
            artists = self.music.fetchItems(self._ekey('artist'), title__contains=artist)
            artist_keys = {a.key for a in artists}
            log.debug('Replacing \'artist\' with grandparentKey__in={}'.format(artist_keys))
            kwargs['grandparentKey__in'] = artist_keys
        return kwargs

    def get_tracks(self, **kwargs):
        return self.music.fetchItems(self._ekey('track'), **self._update_kwargs(kwargs))

    def get_track(self, **kwargs):
        return self.music.fetchItem(self._ekey('track'), **self._update_kwargs(kwargs))

    def find_songs_by_rating_gte(self, rating, **kwargs):
        """
        :param int rating: Song rating on a scale of 0-10
        :return list: List of :class:`plexapi.audio.Track` objects
        """
        return self.get_tracks(userRating__gte=rating, **kwargs)

    def find_song(self, path):
        return self.get_track(media__part__file=path)

    def get_artists(self, name, mode='contains'):
        kwargs = {'title__{}'.format(mode): name}
        return self.music.fetchItems(self._ekey('artist'), **kwargs)

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

    @property
    def playlists(self):
        return {p.title: p for p in self._session.playlists()}

    def create_playlist(self, name, items):
        if not items:
            raise ValueError('An iterable containing one or more tracks/items must be provided')
        return Playlist.create(self._session, name, items)

    def sync_playlist(self, name, **criteria):
        expected = self.get_tracks(**criteria)
        playlists = self.playlists
        if name not in playlists:
            log.info('Creating playlist {} with {:,d} tracks'.format(name, len(expected)))
            log.debug('Creating playlist {} with tracks: {}'.format(name, expected))
            plist = self.create_playlist(name, expected)
        else:
            plist = playlists[name]
            plist_items = plist.items()

            to_remove = []
            for track in plist_items:
                if track not in expected:
                    to_remove.append(track)

            if to_remove:
                log.info('Removing {:,d} tracks from playlist {}'.format(len(to_remove), name))
                for track in to_remove:
                    log.debug('Removing from playlist {}: {}'.format(name, track))
                    plist.removeItem(track)
            else:
                log.log(19, 'Playlist {} does not contain any tracks that should be removed'.format(name))

            to_add = []
            for track in expected:
                if track not in plist_items:
                    to_add.append(track)

            if to_add:
                log.info('Adding {:,d} tracks to playlist {}'.format(len(to_add), name))
                log.debug('Adding to playlist {}: {}'.format(name, to_add))
                plist.addItems(to_add)
            else:
                log.log(19, 'Playlist {} is not missing any tracks'.format(name))

            if not to_add and not to_remove:
                fmt = 'Playlist {} contains {:,d} tracks and is already in sync with the given criteria'
                log.info(fmt.format(name, len(plist_items)))


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
