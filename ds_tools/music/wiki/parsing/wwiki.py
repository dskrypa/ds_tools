"""
:author: Doug Skrypa
"""

import logging
import re
from itertools import chain

from bs4.element import NavigableString

from ....core import datetime_with_tz
from ....utils import DASH_CHARS, num_suffix
from ...name_processing import parse_name, str2list
from .exceptions import *
from .common import *

__all__ = ['expanded_wiki_table', 'parse_discography_page', 'parse_infobox', 'parse_wikipedia_album_page']
log = logging.getLogger(__name__)


def parse_discography_page(uri_path, clean_soup, artist):
    albums, singles = [], []
    try:
        date_comment_rx = parse_discography_page._date_comment_rx
    except AttributeError:
        date_comment_rx = parse_discography_page._date_comment_rx = re.compile(r'^(\S+ \d+\s*, \d{4}).*')

    if clean_soup.find('span', id='Discography'):
        top_lvl_h, sub_h = 'h3', 'h4'
    else:
        top_lvl_h, sub_h = 'h2', 'h3'

    for h2 in clean_soup.find_all(top_lvl_h):
        album_type = h2.text.strip().lower()
        sub_type = None
        if album_type in ('music videos', 'see also'):
            break

        ele = h2.next_sibling
        while hasattr(ele, 'name') and ele.name != top_lvl_h:
            if isinstance(ele, NavigableString):
                ele = ele.next_sibling
                continue
            elif ele.name == sub_h:
                sub_type = ele.text.strip().lower()
            elif ele.name == 'table':
                columns = [th.text.strip() for th in ele.find('tr').find_all('th')]
                if columns[-1] in ('Album', 'Drama'):
                    tracks = []
                    expanded = expanded_wiki_table(ele)
                    # log.debug('Expanded table: {}'.format(expanded))
                    for row in expanded:
                        if row[0].text.strip().isdigit():
                            title_ele = row[1]
                            year_ele = row[0]
                        else:
                            title_ele = row[0]
                            year_ele = row[1]
                        album_ele = row[-1]
                        album_title = album_ele.text.strip()
                        if album_title.lower() == 'non-album single':
                            album_title = None
                        links = link_tuples(chain(title_ele.find_all('a'), album_ele.find_all('a')))
                        track = parse_track_info(
                            1, title_ele.text, uri_path, links=links,
                            include={'links': links, 'album': album_title, 'year': int(year_ele.text.strip())}
                        )
                        # log.debug('Adding type={!r}, sub_type={!r}, track: {}'.format(album_type, sub_type, track))
                        tracks.append(track)
                    singles.append({'type': album_type, 'sub_type': sub_type, 'tracks': tracks})
                else:
                    for i, th in enumerate(ele.find_all('th', scope='row')):
                        links = [(a.text, a.get('href') or '') for a in th.find_all('a')]
                        title = th.text.strip()
                        album = {
                            'title': title, 'links': links, 'type': album_type, 'sub_type': sub_type, 'is_ost': False,
                            'primary_artist': (artist.name, artist._uri_path), 'uri_path': dict(links).get(title),
                            'base_type': album_type, 'wiki': 'en.wikipedia.org', 'num': '{}{}'.format(i, num_suffix(i)),
                            'collaborators': {}, 'misc_info': [], 'language': None, 'is_feature_or_collab': None
                        }

                        for li in th.parent.find('td').find('ul').find_all('li'):
                            key, value = map(str.strip, li.text.split(':', 1))
                            key = key.lower()
                            if key == 'released':
                                try:
                                    value = datetime_with_tz(value, '%B %d, %Y')
                                except Exception as e:
                                    m = date_comment_rx.match(value)
                                    if m:
                                        try:
                                            value = datetime_with_tz(m.group(1), '%B %d, %Y')
                                        except Exception:
                                            msg = 'Unexpected date format on {}: {}'.format(uri_path, value)
                                            raise WikiEntityParseException(msg) from e
                                    else:
                                        msg = 'Unexpected date format on {}: {}'.format(uri_path, value)
                                        raise WikiEntityParseException(msg) from e
                            elif key in ('label', 'format'):
                                value = str2list(value, ',')

                            album[key] = value

                        try:
                            album['year'] = album['released'].year
                        except Exception as e:
                            pass
                        albums.append(album)
            ele = ele.next_sibling
    return albums, singles


def expanded_wiki_table(table_ele):
    """
    In a table containing multiple cells that span multiple rows in a given column, it can be difficult to determine the
    value in that column for an arbitrary row.  This function expands those row-spanning cells to duplicate their values
    in each row that they visually appear in.

    :param table_ele: A bs4 <table> element
    :return list: A list of rows as lists of tr children elements
    """
    rows = []
    row_spans = []
    for tr in table_ele.find_all('tr'):
        eles = [tx for tx in tr.children if not isinstance(tx, NavigableString)]
        # log.debug('{} => ({}) {}'.format(tr, len(eles), eles), extra={'color': 'cyan'})
        if all(ele.name == 'th' for ele in eles) or len(eles) == 1:
            continue
        elif not row_spans:  # 1st row
            row_spans = [(int(ele.get('rowspan') or 0) - 1, ele) for ele in eles]
            row = eles
        else:
            # log.debug('spans ({}): {}'.format(len(row_spans), row_spans), extra={'color': 13})
            row = []
            # ele_iter = iter(eles)
            for i, (col_rows_left, spanned_ele) in enumerate(list(row_spans)):
                if col_rows_left < 1:
                    ele = eles.pop(0)
                    colspan = int(ele.get('colspan', 0))
                    if colspan:
                        ele['colspan'] = colspan - 1
                        eles.insert(0, ele)
                    # try:
                    #     ele = next(ele_iter)
                    # except Exception as e:
                    #     log.error('[{}] Error getting next ele: {}'.format(i, e), extra={'color': 'red'})
                    #     raise e
                    row_spans[i] = (int(ele.get('rowspan') or 0) - 1, ele)
                    row.append(ele)
                else:
                    row_spans[i] = (col_rows_left - 1, spanned_ele)
                    row.append(spanned_ele)
        rows.append(row)
    return rows


def parse_wikipedia_album_page(uri_path, clean_soup, side_info):
    unexpected_num_fmt = 'Unexpected disk number format for {}: {!r}'
    bad_intro_fmt = 'Unexpected album intro sentence format in {}: {!r}'
    album0 = {}
    intro_text = clean_soup.text.strip()
    intro_match = re.match('^(.*?)\s+is\s+(?:a|the)\s+(.*?)\.\s', intro_text)
    if not intro_match:
        raise WikiEntityParseException(bad_intro_fmt.format(uri_path, intro_text[:200]))

    album0['title_parts'] = parse_name(intro_match.group(1))  # base, cjk, stylized, aka, info

    details_str = intro_match.group(2)
    details = list(details_str.split())
    album0['repackage'] = False
    try:
        album0['num'], album0['type'] = album_num_type(details)
    except ValueError as e:
        raise WikiEntityParseException(bad_intro_fmt.format(uri_path, intro_text[:200])) from e

    # links = []
    # for ele in clean_soup.children:
    #     if isinstance(ele, NavigableString):
    #         continue
    #     elif ele.name in ('h1', 'h2', 'h3', 'h4'):
    #         break
    #     links.extend((a.text, a.get('href')) for a in ele.find_all('a'))
    # album0['links'] = links
    album0['released'] = first_side_info_val(side_info, 'released')
    album0['length'] = first_side_info_val(side_info, 'length')
    album0['name'] = side_info.get('name')
    album0['track_lists'] = []

    albums = [album0]
    disk_rx = re.compile(r'^Dis[ck]\s+(\S+)\s*[{}]?\s*(.*)$'.format(DASH_CHARS + ':'), re.IGNORECASE)
    album = album0
    for track_tbl in clean_soup.find_all('table', class_='tracklist'):
        last_ele = track_tbl.previous_sibling
        while isinstance(last_ele, NavigableString):
            last_ele = last_ele.previous_sibling

        if last_ele and last_ele.name == 'h3':
            title_parts = parse_name(last_ele.text.strip())
            repkg_title = title_parts[0]
            album = {
                'track_lists': [], 'title_parts': title_parts, 'repackage': True, 'repackage_of_href': uri_path,
                'repackage_of_title': repkg_title
            }
            if len(albums) == 1:
                album0['repackage_href'] = uri_path
                album0['repackage_title'] = repkg_title
            albums.append(album)

        section_th = track_tbl.find(lambda ele: ele.name == 'th' and ele.get('colspan'))
        section = section_th.text.strip() if section_th else None
        if section and section.lower().startswith(('disk', 'disc')):
            m = disk_rx.match(section)
            if not m:
                raise WikiEntityParseException(unexpected_num_fmt.format(uri_path, section))
            try:
                disk = NUM2INT[m.group(1).lower()]
            except KeyError as e:
                raise WikiEntityParseException(unexpected_num_fmt.format(uri_path, m.group(1))) from e
            section = m.group(2).strip() or None
        else:
            disk = 1

        tracks = []
        for tr in track_tbl.find_all('tr'):
            tds = tr.find_all('td')
            if len(tds) >= 3:
                tracks.append(parse_track_info(tds[0].text, tds[1].text, uri_path, tds[-1].text.strip()))

        album['track_lists'].append({'section': section, 'tracks': tracks, 'disk': disk})

    for album in albums:
        album['artists'] = side_info.get('artist', {})

    return albums


def parse_infobox(infobox):
    """
    Parse the 'infobox' element from a wiki page into a more easily used data format

    :param infobox: Beautiful soup <table class='infobox'> element
    :return dict: The parsed data
    """
    parsed = {}
    for i, tr in enumerate(infobox.find_all('tr')):
        # log.debug('Processing tr: {}'.format(tr))
        if i == 0:
            parsed['name'] = tr.text.strip()
        elif i == 1:
            continue    # Image
        elif i == 2 and tr.find('th').get('colspan'):
            try:
                parsed['type'], artist = map(str.strip, tr.text.strip().split(' by '))
            except Exception as e:
                log.debug('Error processing infobox row {!r}: {}'.format(tr, e))
                raise e

            for a in tr.find_all('a'):
                if a.text == artist:
                    href = a.get('href') or ''
                    parsed['artist'] = {artist: href[6:] if href.startswith('/wiki/') else href}
                    break
            else:
                parsed['artist'] = {artist: None}
        else:
            th = tr.find('th')
            if not th or th.get('colspan'):
                break
            key = th.text.strip().lower()
            val_ele = tr.find('td')

            if key == 'released':
                value = []
                val = val_ele.text.strip()
                try:
                    dt = datetime_with_tz(val, '%d %B %Y')
                except Exception as e:
                    raise WikiEntityParseException('Unexpected release date format: {!r}'.format(val)) from e
                else:
                    value.append((dt, None))
            elif key == 'length':
                value = [(val_ele.text.strip(), None)]
            elif key == 'also known as':
                value = [val for val in val_ele.stripped_strings if val]
            elif key in ('agency', 'associated', 'composer', 'current', 'label', 'writer'):
                anchors = list(val_ele.find_all('a'))
                if anchors:
                    value = dict(link_tuples(anchors))
                    # value = {a.text: a.get('href') for a in anchors}
                else:
                    ele_children = list(val_ele.children)
                    if not isinstance(ele_children[0], NavigableString) and ele_children[0].name == 'ul':
                        value = {li.text: None for li in ele_children[0].find_all('li')}
                    else:
                        value = {name: None for name in str2list(val_ele.text)}
            else:
                value = val_ele.text.strip()

            parsed[key] = value
    return parsed
