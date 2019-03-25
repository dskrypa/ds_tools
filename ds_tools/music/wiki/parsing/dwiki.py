"""
:author: Doug Skrypa
"""

import logging
import re

from ....unicode import LangCat
from ...name_processing import eng_cjk_sort, split_name, str2list
from .exceptions import *
from .common import *

__all__ = ['parse_artist_osts', 'parse_drama_wiki_info_list', 'parse_ost_page']
log = logging.getLogger(__name__)


def parse_artist_osts(uri_path, clean_soup, artist):
    try:
        ost_ul = clean_soup.find('span', id='TV_Show_Theme_Songs').parent.find_next('ul')
    except Exception as e:
        raise WikiEntityParseException('Unable to find TV_Show_Theme_Songs section in {}'.format(uri_path)) from e

    albums = []
    for li in ost_ul.find_all('li'):
        try:
            year = int(li.text[-5:-1])
        except Exception:
            year = None
        links = [(a.text, a.get('href') or '') for a in li.find_all('a')]
        for text, href in links:
            if href and '_ost' in href.lower() or ' ost' in text.lower():
                album = {
                    'title': text, 'type': 'OST', 'is_ost': True, 'uri_path': href, 'base_type': 'osts',
                    'wiki': 'wiki.d-addicts.com', 'collaborators': {}, 'misc_info': [], 'language': None,
                    'primary_artist': (artist.name, artist._uri_path) if artist else (None, None),
                    'is_feature_or_collab': None, 'year': year
                }
                albums.append(album)
                break
        else:
            li_text = li.text
            if not any(a['title'] in li_text for a in albums):  # They don't repeat links for the same target
                log.warning('No OST found in li on {}: {}'.format(uri_path, li))
    return albums


def parse_ost_page(uri_path, clean_soup):
    try:
        first_h2 = clean_soup.find('h2')
    except AttributeError:
        first_h2 = None
    if not first_h2:
        raise WikiEntityParseException('Unable to find first OST part section in {}'.format(uri_path))

    track_lists = []
    h2 = first_h2
    while True:
        # log.debug('Processing section: {}'.format(h2))
        if not h2 or h2.next_element.get('id', '').lower() in ('see_also', 'insert_songs'):
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
                if len(name_parts) == 1 and LangCat.categorize(name_parts[0]) == LangCat.MIX:
                    name_parts = split_name(name_parts[0], unused=True)
                elif all(part.lower().endswith('(inst.)') for part in name_parts):
                    name_parts = [part[:-7].strip() for part in name_parts]
                    name_parts.append('Inst.')

                track = parse_track_info(tds[0].text, name_parts, uri_path, include={'from_ost': True})
                # track['collaborators'] = str2list(tds[2].text.strip())
                track['collaborators'], track['produced_by'] = split_artist_list(tds[2].text.strip(), context=uri_path)
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
        if i == 0 and key not in ('title', 'name', 'group name'):
            return None
        elif key in ('title', 'name', 'group name'):
            try:
                value = eng_cjk_sort(map(str.strip, value.split('/')), permissive=True)
            except Exception as e:
                pass
        elif key in ('release date', 'birthdate'):
            if key == 'birthdate':
                try:
                    bday_rx = parse_drama_wiki_info_list._bday_rx
                except AttributeError:
                    bday_rx = parse_drama_wiki_info_list._bday_rx = re.compile(r'^(.*)\s\(age.*\)$', re.IGNORECASE)
                m = bday_rx.match(value)
                if m:
                    value = m.group(1)
            try:
                value = parse_date(value, try_dateparser=True, source=uri_path)
            except UnexpectedDateFormat as e:
                log.debug('Error parsing {}: {}'.format(key, e))
            except Exception as e:
                log.debug('Error parsing {} {!r} for {}: {}'.format(key, value, uri_path, e))
        elif key == 'language':
            value = str2list(value)
        elif key == 'artist':
            # try:
            #     prod_by_rx = parse_drama_wiki_info_list._prod_by_rx
            # except AttributeError:
            #     prod_by_rx = parse_drama_wiki_info_list._prod_by_rx = re.compile(
            #         r'^(.*)\s\(Prod(?:\.|uced)? by\s+(.*)\)$', re.IGNORECASE
            #     )
            links = dict(link_tuples(li.find_all('a')))
            value, info['produced_by'] = split_artist_list(value, context=uri_path, link_dict=links)
            # artists = str2list(value)
            # value = []
            # for artist in artists:
            #     m = prod_by_rx.match(artist)
            #     if m:
            #         artist, prod_by = m.groups()
            #     else:
            #         prod_by = None
            #
            #     try:
            #         soloist, of_group = artist.split(' of ')
            #     except Exception as e:
            #         try:
            #             value.append({'artist': split_name(artist, permissive=True), 'prod_by': prod_by})
            #         except ValueError as e1:
            #             raise WikiEntityParseException('Error parsing info list in {}: {}'.format(uri_path, e1)) from e1
            #     else:
            #         try:
            #             value.append({
            #                 'artist': split_name(soloist), 'of_group': split_name(of_group), 'prod_by': prod_by
            #             })
            #         except ValueError as e:
            #             raise WikiEntityParseException('Error parsing info list in {}: {}'.format(uri_path, e)) from e
        elif key == 'also known as':
            value = str2list(value)
        elif key == 'original soundtrack':
            links = dict(link_tuples(li.find_all('a')))
            value = {value: links.get(value)}

        info[key] = value
    return info
