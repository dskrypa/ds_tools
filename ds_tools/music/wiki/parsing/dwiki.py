"""
:author: Doug Skrypa
"""

import logging

from ....core import datetime_with_tz
from ...name_processing import *
from .exceptions import *
from .common import *

__all__ = ['parse_drama_wiki_info_list', 'parse_ost_page']
log = logging.getLogger(__name__)


def parse_ost_page(uri_path, clean_soup):
    first_h2 = clean_soup.find('h2')
    if not first_h2:
        raise WikiEntityParseException('Unable to find first OST part section in {}'.format(uri_path))

    track_lists = []
    h2 = first_h2
    while True:
        # log.debug('Processing section: {}'.format(h2))
        if not h2 or h2.next_element.get('id', '').lower() == 'see_also':
            break

        section = h2.text
        info_ul = h2.find_next_sibling('ul')
        if not info_ul:
            break
        info = parse_drama_wiki_info_list(uri_path, info_ul)
        if info is None:
            return track_lists

        tracks = []
        track_table = info_ul.find_next_sibling('table')
        for tr in track_table.find_all('tr'):
            tds = tr.find_all('td')
            if tds:
                name_parts = list(tds[1].stripped_strings)
                if len(name_parts) == 1 and categorize_langs(name_parts)[0] == LangCat.MIX:
                    name_parts = split_name(name_parts[0], unused=True)
                elif all(part.lower().endswith('(inst.)') for part in name_parts):
                    name_parts = [part[:-7].strip() for part in name_parts]
                    name_parts.append('Inst.')

                track = parse_track_info(tds[0].text, name_parts, uri_path, include={'from_ost': True})
                track['collaborators'] = str2list(tds[2].text.strip())
                tracks.append(track)

        track_lists.append({'section': section, 'tracks': tracks, 'info': info})
        h2 = h2.find_next_sibling('h2')

    return track_lists


def parse_drama_wiki_info_list(uri_path, info_ul):
    info = {}
    for i, li in enumerate(info_ul.find_all('li')):
        try:
            key, value = map(str.strip, li.text.strip().split(':', 1))
        except ValueError as e:
            fmt = 'Error splitting key:value pair {!r} from {}: {}'
            raise WikiEntityParseException(fmt.format(li.text.strip(), uri_path, e)) from e
        key = key.lower()
        if i == 0 and key != 'title':
            return None
        elif key == 'title':
            try:
                value = eng_cjk_sort(map(str.strip, value.split('/')), permissive=True)
            except Exception as e:
                pass
        elif key == 'release date':
            try:
                value = datetime_with_tz(value, '%Y-%b-%d')
            except Exception as e:
                log.debug('Error parsing release date {!r} for {}: {}'.format(value, uri_path, e))
                pass
        elif key == 'language':
            value = str2list(value)
        elif key == 'artist':
            artists = str2list(value, pat='(?: and |,|;|&| feat\.? )')
            value = []
            for artist in artists:
                try:
                    soloist, of_group = artist.split(' of ')
                except Exception as e:
                    value.append({'artist': split_name(artist)})
                else:
                    value.append({'artist': split_name(soloist), 'of_group': split_name(of_group)})
        elif key == 'also known as':
            value = str2list(value)
        elif key == 'original soundtrack':
            links = dict(link_tuples(li.find_all('a')))
            value = {value: links.get(value)}

        info[key] = value
    return info
