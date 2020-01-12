"""
Module for syncing Plex ratings with ratings stored in ID3 tags

Note on fetchItems:
The kwargs to fetchItem/fetchItems use __ to access nested attributes, but the only nested attributes available are
those that are returned in the items in ``plex._session.query(plex._ekey(search_type))``, not the higher level objects.
Example available attributes::\n
    >>> data = plex._session.query(plex._ekey('track'))
    >>> media = [c for c in data[0]]
    >>> for m in media:
    ...     m
    ...     m.attrib
    ...     print(', '.join(sorted(m.attrib)))
    ...     for part in m:
    ...         part
    ...         part.attrib
    ...         print(', '.join(sorted(part.attrib)))
    ...
    <Element 'Media' at 0x000001E4E3971458>
    {'id': '76273', 'duration': '238680', 'bitrate': '320', 'audioChannels': '2', 'audioCodec': 'mp3', 'container': 'mp3'}
    audioChannels, audioCodec, bitrate, container, duration, id
    <Element 'Part' at 0x000001E4E48D9458>
    {'id': '76387', 'key': '/library/parts/76387/1555183134/file.mp3', 'duration': '238680', 'file': '/path/to/song.mp3', 'size': '9773247', 'container': 'mp3', 'hasThumbnail': '1'}
    container, duration, file, hasThumbnail, id, key, size

    >>> data = plex._session.query(plex._ekey('album'))
    >>> data[0]
    <Element 'Directory' at 0x000001E4E3C92458>
    >>> print(', '.join(sorted(data[0].attrib.keys())))
    addedAt, guid, index, key, loudnessAnalysisVersion, originallyAvailableAt, parentGuid, parentKey, parentRatingKey, parentThumb, parentTitle, ratingKey, summary, thumb, title, type, updatedAt, year
    >>> elements = [c for c in data[0]]
    >>> for e in elements:
    ...     e
    ...     e.attrib
    ...     for sub_ele in e:
    ...         sub_ele
    ...         sub_ele.attrib
    ...
    <Element 'Genre' at 0x000001E4E3C929F8>
    {'tag': 'K-pop'}

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


Object and element attributes and elements available for searching:
 - track:
    - attributes: addedAt, duration, grandparentGuid, grandparentKey, grandparentRatingKey, grandparentThumb,
      grandparentTitle, guid, index, key, originalTitle, parentGuid, parentIndex, parentKey, parentRatingKey,
      parentThumb, parentTitle, ratingKey, summary, thumb, title, type, updatedAt
    - elements: media
 - album:
    - attributes: addedAt, guid, index, key, loudnessAnalysisVersion, originallyAvailableAt, parentGuid, parentKey,
      parentRatingKey, parentThumb, parentTitle, ratingKey, summary, thumb, title, type, updatedAt, year
    - elements: genre
 - artist:
    - attributes: addedAt, guid, index, key, lastViewedAt, ratingKey, summary, thumb, title, type, updatedAt,
      userRating, viewCount
    - elements: genre
 - media:
    - attributes: audioChannels, audioCodec, bitrate, container, duration, id
    - elements: part
 - genre:
    - attributes: tag
 - part:
    - attributes: container, duration, file, hasThumbnail, id, key, size

:author: Doug Skrypa
"""

import logging
import re
from collections import defaultdict
from getpass import getpass
from pathlib import Path

from plexapi.myplex import MyPlexAccount
from plexapi.playlist import Playlist
from plexapi.server import PlexServer
from plexapi.utils import SEARCHTYPES
from requests import Session
from urllib3 import disable_warnings as disable_urllib3_warnings

from ..compat import cached_property
from ..core import InputValidationException
from ..unicode import LangCat
from ..output import short_repr, bullet_list
from .files import SongFile
from .patches import apply_plex_patches
from .utils import stars

__all__ = ['LocalPlexServer']
log = logging.getLogger(__name__)

disable_urllib3_warnings()
apply_plex_patches()

CUSTOM_FILTERS = {
    'genre': ('album', 'genre__tag', {'track': 'parentKey'}),
    'album': ('album', 'title', {'track': 'parentKey'}),
    'artist': ('artist', 'title', {'track': 'grandparentKey', 'album': 'parentKey'}),
    'in_playlist': ('playlist', 'title', {})
}
CUSTOM_OPS = {
    '__like': 'sregex',
    '__like_exact': 'sregex',
    '__not_like': 'nsregex'
}


class LocalPlexServer:
    def __init__(self, url=None, user=None, server_path_root=None, cache_dir='~/.plex', music_library=None):
        self._cache = Path(cache_dir).expanduser().resolve()
        if not self._cache.exists():
            self._cache.mkdir(parents=True)

        self.user = user

        if not url:
            url_path = self._cache.joinpath('server_url.txt')
            if url_path.exists():
                url = url_path.open('r').read().strip()
            if not url:
                raise ValueError('A server URL must be provided or be in {}'.format(url_path.as_posix()))
        self.url = url

        if not server_path_root:
            root_path = self._cache.joinpath('server_path_root.txt')
            if root_path.exists():
                server_path_root = root_path.open('r').read().strip()
            if not server_path_root:
                raise ValueError('A server root path must be provided or be in {}'.format(root_path.as_posix()))
        self.server_root = Path(server_path_root)

        music_library_path = self._cache.joinpath('music_library_name.txt')
        if not music_library:
            if music_library_path.exists():
                music_library = music_library_path.open('r').read().strip()
            else:
                music_library = 'Music'
        else:
            if not music_library_path.exists():
                with music_library_path.open('w') as f:
                    f.write(music_library + '\n')
        self.music_library = music_library

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
        return self._session.library.section(self.music_library)

    def _ekey(self, search_type):
        return '/library/sections/1/all?type={}'.format(SEARCHTYPES[search_type])

    def _update_filters(self, obj_type, kwargs):
        """
        Update the kwarg search filters for a fetchItem/fetchItems call using custom search filters.

        Implemented custom filters:
         - *__like: Automatically compiles the given str value as a regex pattern and replaces 'like' with the custom
           sregex filter function, which uses pattern.search() instead of re.match()
         - *__not_like: Like __like, but translates to nsregex
         - genre: Plex stores genres at the album and artist level rather than the track level - this filter first runs
           a search for albums that match the given value, then adds a filter to the track search so that only tracks
           that are in the albums with the given genre are returned.
         - artist/album: Rather than needing to chain searches manually where artist/album objects are passed as the
           values, they can now be provided as strings.  Similar to the genre search, a separate search is run first for
           finding artists/albums that match the given value, then tracks from/in the given criteria are found by using
           the parentKey__in/grandparentKey__in filters, respectfully.  In theory, this should be more efficient than
           using the parentTitle/grandparentTitle filters, since any regex operations only need to be done on the
           album/artist titles once instead of on each track's album/artist titles, and the track search can use a O(1)
           set lookup against the discovered parent/grandparent keys.

        :param dict kwargs: The kwargs that were passed to :meth:`.get_tracks` or a similar method
        :return dict: Modified kwargs with custom search filters
        """
        exclude_rated_dupes = kwargs.pop('exclude_rated_dupes', False)
        # Replace custom/shorthand ops with the real operators
        for filter_key, filter_val in sorted(kwargs.items()):
            keyword = next((val for val in CUSTOM_OPS if filter_key.endswith(val)), None)
            if keyword:
                kwargs.pop(filter_key)
                target_key = '{}__{}'.format(filter_key[:-len(keyword)], CUSTOM_OPS[keyword])
                if keyword == '__like' and isinstance(filter_val, str):
                    filter_val = filter_val.replace(' ', '.*?')
                filter_val = re.compile(filter_val, re.IGNORECASE) if isinstance(filter_val, str) else filter_val
                log.debug('Replacing custom op {!r} with {}={}'.format(filter_key, target_key, short_repr(filter_val)))
                kwargs[target_key] = filter_val

        # Perform intermediate searches that are necessary for custom filters
        filter_repl_fmt = 'Replacing custom filter {!r} with {}={}'
        for kw, (ekey, field, targets) in sorted(CUSTOM_FILTERS.items()):
            us_key = '{}__'.format(kw)
            try:
                target_key = '{}__in'.format(targets[obj_type])
            except KeyError:
                if kw == 'genre':   # tracks need to go by their parents' genre, but albums/artists can use their own
                    for filter_key in {k for k in kwargs if k == kw or k.startswith(us_key)}:
                        if filter_key.startswith('genre') and not filter_key.startswith('genre__tag'):
                            target_key = filter_key.replace('genre', 'genre__tag', 1)
                            filter_val = kwargs.pop(filter_key)
                            log.debug(filter_repl_fmt.format(filter_key, target_key, short_repr(filter_val)))
                            kwargs[target_key] = filter_val
                elif kw == 'in_playlist':
                    target_key = 'key__in'
                    for filter_key in {k for k in kwargs if k == kw or k.startswith(us_key)}:
                        filter_val = kwargs.pop(filter_key)
                        lc_val = filter_val.lower()
                        for pl_name, playlist in self.playlists.items():
                            if pl_name.lower() == lc_val:
                                log.debug(filter_repl_fmt.format(filter_key, target_key, short_repr(filter_val)))
                                keys = {track.key for track in playlist.items()}
                                if target_key in kwargs:
                                    keys = keys.intersection(kwargs[target_key])
                                    log.debug('Merged filter={!r} values => {}'.format(target_key, short_repr(keys)))
                                kwargs[target_key] = keys
                                break
                        else:
                            raise ValueError('Invalid playlist: {!r}'.format(filter_val))

                continue

            kw_keys = {k for k in kwargs if k == kw or k.startswith(us_key)}
            if kw_keys:
                ekey_filters = {}
                for filter_key in kw_keys:
                    filter_val = kwargs.pop(filter_key)
                    try:
                        base, op = filter_key.rsplit('__', 1)
                    except ValueError:
                        op = 'contains'
                    else:
                        if base.endswith('__not'):
                            op = 'not__' + op

                    ekey_filters['{}__{}'.format(field, op)] = filter_val

                fmt = 'Performing intermediate search for custom filters={}: ekey={!r} with filters={}'
                custom_filter_keys = '+'.join(sorted(kw_keys))
                filter_repr = ', '.join('{}={}'.format(k, short_repr(v)) for k, v in ekey_filters.items())
                log.debug(fmt.format(ekey, custom_filter_keys, filter_repr))
                results = self.music.fetchItems(self._ekey(ekey), **ekey_filters)
                if obj_type == 'album' and target_key == 'key__in':
                    keys = {'{}/children'.format(a.key) for a in results}
                else:
                    keys = {a.key for a in results}

                fmt = 'Replacing custom filters {} with {}={}'
                log.debug(fmt.format(custom_filter_keys, target_key, short_repr(keys)))
                if target_key in kwargs:
                    keys = keys.intersection(kwargs[target_key])
                    log.debug('Merging {} values: {}'.format(target_key, short_repr(keys)))
                kwargs[target_key] = keys

        # If excluding rated dupes, search for the tracks that were rated and have the same titles as unrated tracks
        if exclude_rated_dupes and obj_type == 'track' and 'userRating' in kwargs:
            dupe_kwargs = kwargs.copy()
            dupe_kwargs.pop('userRating')
            dupe_kwargs['userRating__gte'] = 1
            rated_tracks = self.music.fetchItems(self._ekey('track'), **dupe_kwargs)
            rated_tracks_by_artist_key = defaultdict(set)
            for track in rated_tracks:
                rated_tracks_by_artist_key[track.grandparentKey].add(track.title.lower())

            pat = re.compile(r'(.*)\((?:Japanese|JP|Chinese|Mandarin)\s*(?:ver\.?(?:sion))?\)$', re.IGNORECASE)

            def _filter(elem_attrib):
                titles = rated_tracks_by_artist_key[elem_attrib['grandparentKey']]
                if not titles:
                    return True
                title = elem_attrib['title'].lower()
                if title in titles:
                    return False
                m = pat.match(title)
                if m and m.group(1).strip() in titles:
                    return False
                part = next((t for t in titles if t.startswith(title) or title.startswith(t)), None)
                if not part:
                    return True
                elif len(part) > len(title):
                    return title not in LangCat.split(part)
                return part not in LangCat.split(title)

            # kwargs['custom__custom'] = lambda a: a['title'] not in rated_tracks_by_artist_key[a['grandparentKey']]
            kwargs['custom__custom'] = _filter

        return kwargs

    def get_tracks(self, **kwargs):
        return self.music.fetchItems(self._ekey('track'), **self._update_filters('track', kwargs))

    def get_track(self, **kwargs):
        return self.music.fetchItem(self._ekey('track'), **self._update_filters('track', kwargs))

    def find_songs_by_rating_gte(self, rating, **kwargs):
        """
        :param int rating: Song rating on a scale of 0-10
        :return list: List of :class:`plexapi.audio.Track` objects
        """
        return self.get_tracks(userRating__gte=rating, **kwargs)

    def find_song(self, path):
        return self.get_track(media__part__file=path)

    def get_artists(self, name, mode='contains', **kwargs):
        kwargs.setdefault('title__{}'.format(mode), name)
        return self.music.fetchItems(self._ekey('artist'), **self._update_filters('artist', kwargs))

    def get_albums(self, name, mode='contains', **kwargs):
        kwargs.setdefault('title__{}'.format(mode), name)
        return self.music.fetchItems(self._ekey('album'), **self._update_filters('album', kwargs))

    def find_objects(self, obj_type, **kwargs):
        return self.music.fetchItems(self._ekey(obj_type), **self._update_filters(obj_type, kwargs))

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
        add_fmt = 'Adding {:,d} tracks to playlist {} ({:,d} tracks => {:,d}):'
        rm_fmt = 'Removing {:,d} tracks from playlist {} ({:,d} tracks => {:,d}):'
        if name not in playlists:
            log.info('Creating playlist {} with {:,d} tracks'.format(name, len(expected)), extra={'color': 10})
            log.debug('Creating playlist {} with tracks: {}'.format(name, expected))
            plist = self.create_playlist(name, expected)
        else:
            plist = playlists[name]
            plist_items = plist.items()
            size = len(plist_items)

            to_rm = []
            for track in plist_items:
                if track not in expected:
                    to_rm.append(track)

            if to_rm:
                log.info(rm_fmt.format(len(to_rm), name, size, size - len(to_rm)), extra={'color': 13})
                print(bullet_list(to_rm))
                size -= len(to_rm)
                # for track in to_remove:
                #     plist.removeItem(track)
                plist.removeItems(to_rm)
            else:
                log.log(19, 'Playlist {} does not contain any tracks that should be removed'.format(name))

            to_add = []
            for track in expected:
                if track not in plist_items:
                    to_add.append(track)

            if to_add:
                log.info(add_fmt.format(len(to_add), name, size, size + len(to_add)), extra={'color': 14})
                print(bullet_list(to_add))
                plist.addItems(to_add)
                size += len(to_add)
            else:
                log.log(19, 'Playlist {} is not missing any tracks'.format(name))

            if not to_add and not to_rm:
                fmt = 'Playlist {} contains {:,d} tracks and is already in sync with the given criteria'
                log.info(fmt.format(name, len(plist_items)), extra={'color': 11})


def print_song_info(songs):
    for song in songs:
        print('{} - {} - {} - {}'.format(stars(song.userRating), song.artist().title, song.album().title, song.title))


if __name__ == '__main__':
    from .patches import apply_mutagen_patches
    apply_mutagen_patches()
