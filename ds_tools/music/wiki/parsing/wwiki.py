"""
:author: Doug Skrypa
"""

import logging
import re
from itertools import chain

from bs4.element import NavigableString

from ....unicode import LangCat
from ....utils import DASH_CHARS, num_suffix, soupify, unsurround
from ...name_processing import parse_name, str2list, split_name
from .exceptions import *
from .common import *

__all__ = [
    'expanded_wiki_table', 'parse_discography_page', 'parse_infobox', 'parse_wikipedia_album_page',
    'parse_wikipedia_group_members'
]
log = logging.getLogger(__name__)


def parse_discography_page(uri_path, clean_soup, artist):
    albums, singles = [], []
    try:
        date_comment_rx = parse_discography_page._date_comment_rx
        br_split_rx = parse_discography_page._br_split_rx
    except AttributeError:
        date_comment_rx = parse_discography_page._date_comment_rx = re.compile(r'^(\S+ \d+\s*, \d{4}).*')
        br_split_rx = parse_discography_page._br_split_rx = re.compile(r'<br/?>')

    if clean_soup.find('span', id='Discography'):
        top_lvl_h, sub_h = 'h3', 'h4'
    else:
        top_lvl_h, sub_h = 'h2', 'h3'

    for h2 in clean_soup.find_all(top_lvl_h):
        album_type = h2.text.strip().lower()
        sub_type = None
        if album_type in ('music videos', 'see also', 'videography'):
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
                if columns[-1] in ('Album', 'Drama'):                                               # It is a single
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

                        lines = list(map(unsurround, (soupify(ln).text for ln in br_split_rx.split(str(title_ele)))))
                        while any(line.endswith(',') for line in lines):
                            for i, line in enumerate(lines):
                                if line.endswith(',') and i != len(lines):
                                    lines[i] = '{} {}'.format(line, lines.pop(i+1))
                            else:
                                if lines[-1].endswith(','):
                                    break

                        if LangCat.categorize(lines[0]) == LangCat.MIX:
                            line = lines.pop(0)
                            lines = list(split_name(line, allow_cjk_mix=True)) + lines

                        track = parse_track_info(
                            1, lines, uri_path, links=links,
                            include={'links': links, 'album': album_title, 'year': int(year_ele.text.strip())}
                        )
                        # fmt = 'Single info from {} - {} - type={!r} sub_type={!r} album={!r} lines={!r}\n==> track={}'
                        # log.debug(fmt.format(artist, uri_path, album_type, sub_type, album_title, lines, track))
                        tracks.append(track)
                    singles.append({'type': album_type, 'sub_type': sub_type, 'tracks': tracks})
                else:                                                                               # It is an album
                    for i, th in enumerate(ele.find_all('th', scope='row')):
                        links = link_tuples(th.find_all('a'))
                        title = th.text.strip()
                        fmt = 'Processing type={!r} sub_type={!r} th={!r} on {}'
                        log.debug(fmt.format(album_type, sub_type, title, uri_path))
                        album = {
                            'title': title, 'links': links, 'type': album_type, 'sub_type': sub_type, 'is_ost': False,
                            'primary_artist': (artist.name, artist._uri_path) if artist else (None, None),
                            'uri_path': dict(links).get(title), 'base_type': album_type, 'wiki': 'en.wikipedia.org',
                            'num': '{}{}'.format(i, num_suffix(i)), 'collaborators': {}, 'misc_info': [],
                            'language': None, 'is_feature_or_collab': None, 'title_parts': parse_name(title)
                        }

                        for li in th.parent.find('td').find('ul').find_all('li'):
                            key, value = map(str.strip, li.text.split(':', 1))
                            key = key.lower()
                            if key == 'released':
                                try:
                                    value = parse_date(value, source=uri_path)
                                except Exception as e0:
                                    m = date_comment_rx.match(value)
                                    if m:
                                        try:
                                            value = parse_date(m.group(1), source=uri_path)
                                        except UnexpectedDateFormat as e:
                                            raise e
                                        except Exception as e:
                                            msg = 'Unexpected date format on {}: {}'.format(uri_path, value)
                                            raise UnexpectedDateFormat(msg) from e
                                    else:
                                        if isinstance(e0, UnexpectedDateFormat):
                                            raise e0
                                        msg = 'Unexpected date format on {}: {}'.format(uri_path, value)
                                        raise UnexpectedDateFormat(msg) from e0
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
    details_str = details_str.replace('full length', 'full-length').replace('mini-album', 'mini album')
    details = list(details_str.split())
    album0['repackage'] = False
    try:
        album0['num'], album0['type'] = album_num_type(details)
    except ValueError as e:
        log.debug('In {}, parsed: title_parts={!r}, details={!r}'.format(uri_path, album0['title_parts'], details))
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
        album['artists'] = side_info.get('artist', [])

    return albums


def parse_infobox(infobox, uri_path, client):
    """
    Parse the 'infobox' element from a wiki page into a more easily used data format

    :param infobox: Beautiful soup <table class='infobox'> element
    :return dict: The parsed data
    """
    parsed = {}
    for i, tr in enumerate(infobox.find_all('tr')):
        # log.debug('Processing tr {}: {}'.format(i, tr))
        if i == 0:
            parsed['name'] = tr.text.strip()
            continue
        elif i == 1:
            continue    # Image

        th = tr.find('th')
        if not th or (th.get('colspan') and i != 2):
            break
        key = th.text.strip().lower()
        if i == 2:
            if key != 'background information':
                try:
                    parsed['type'], artist = map(str.strip, tr.text.strip().split(' by '))
                except Exception as e:
                    # log.debug('Error processing infobox row {!r}: {}'.format(tr, e))
                    # raise e
                    pass
                else:
                    for a in tr.find_all('a'):
                        if a.text == artist:
                            href = a.get('href') or ''
                            href = href[6:] if href.startswith('/wiki/') else href
                            parsed['artist'] = [{'artist': artist, 'artist_href': href}]
                            break
                    else:
                        parsed['artist'] = [{'artist': artist, 'artist_href': None}]

                    continue
            else:
                continue

        val_ele = tr.find('td')
        if val_ele is None:
            continue

        if key == 'released':
            value = []
            for val in val_ele.stripped_strings:
                val = re.sub('\s+', ' ', val)
                try:
                    dt = parse_date(val)
                except UnexpectedDateFormat as e:
                    if value and not value[-1][1]:
                        value[-1] = (value[-1][0], unsurround(val))
                    else:
                        raise e
                except Exception as e:
                    raise UnexpectedDateFormat('Unexpected release date format: {!r}'.format(val)) from e
                else:
                    value.append((dt, None))
        elif key == 'length':
            value = [(val_ele.text.strip(), None)]
        elif key == 'also known as':
            value = [val for val in val_ele.stripped_strings if val]
        elif key == 'born':
            for j, val in enumerate(val_ele.stripped_strings):
                if j == 0:
                    try:
                        dt = parse_date(val)
                    except Exception as e:
                        if client.is_any_category(uri_path, ['group']):
                            break
                        parsed['birth_name'] = [split_name(val)]
                    else:
                        parsed['birth_date'] = dt
                elif '(age' in val:
                    pass
                else:
                    try:
                        dt = parse_date(val)
                    except Exception as e:
                        parsed['birth_place'] = val
                    else:
                        parsed['birth_date'] = dt

            # log.info('Parsed "born" section: {}'.format(parsed), extra={'color': 123})
            continue
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
            try:
                value = val_ele.text.strip()
            except AttributeError as e:
                log.error('Error parsing ele on {}'.format(uri_path))
                raise e

        parsed[key] = value
    return parsed


def parse_wikipedia_group_members(artist, clean_soup):
    members_span = clean_soup.find('span', id='Members')
    if members_span:
        members_h2 = members_span.parent
        members_container = members_h2
        for sibling in members_h2.next_siblings:
            if sibling.name in ('ul', 'table'):
                members_container = sibling
                break

        if members_container.name == 'ul':
            for li in members_container.find_all('li'):
                li_text = li.text.strip()
                if '—' in li_text:
                    member, roles = li_text.split('—', 1)
                else:
                    member = li_text

                base, cjk, stylized, aka, info = parse_name(member)
                yield None, (base, cjk)
        elif members_container.name == 'table':
            fmt = '{}: Found unexpected/unencountered member table on page: {}'
            raise WikiEntityParseException(fmt.format(artist, artist.url))
