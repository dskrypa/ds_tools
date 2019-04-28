"""
:author: Doug Skrypa
"""

import logging
import re

from ....unicode import LangCat, romanized_permutations
from ....utils import common_suffix
from ...name_processing import eng_cjk_sort, split_name, str2list
from .exceptions import *
from .common import *

__all__ = ['parse_artist_osts', 'parse_drama_wiki_info_list', 'parse_ost_page']
log = logging.getLogger(__name__)


def parse_artist_osts(uri_path, clean_soup, artist):
    excs = []
    for span_id in ('TV_Show_Theme_Songs', 'TV_Shows_Theme_Songs'):
        try:
            ost_ul = clean_soup.find('span', id=span_id).parent.find_next('ul')
        except Exception as e:
            excs.append(e)
        else:
            break
    else:
        raise WikiEntityParseException('Unable to find TV_Show_Theme_Songs section in {}'.format(uri_path)) from excs[0]

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


def parse_ost_page(uri_path, clean_soup, client):
    try:
        first_h2 = clean_soup.find('h2')
    except AttributeError:
        first_h2 = None
    if not first_h2:
        raise WikiEntityParseException('Unable to find first OST part section in {}'.format(uri_path))

    anchors = tuple(clean_soup.find_all('a'))
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
        info = parse_drama_wiki_info_list(uri_path, info_ul, client)
        if info is None:
            return track_lists

        tracks = []
        page_eng_cjk_artists = set()
        track_table = info_ul.find_next_sibling('table')
        for i, tr in enumerate(track_table.find_all('tr')):
            tds = tr.find_all('td')
            if tds:
                to_include = {'from_ost': True}
                name_parts = list(tds[1].stripped_strings)
                if len(name_parts) == 1 and LangCat.categorize(name_parts[0]) == LangCat.MIX:
                    try:
                        name_parts = split_name(name_parts[0], unused=True)
                    except ValueError as e:
                        err_msg = 'Error splitting name={!r} from {}'.format(name_parts[0], uri_path)
                        _eng = []
                        _cjk = []
                        lang_sort_worked = False
                        for part in name_parts[0].split():
                            if LangCat.categorize(part) == LangCat.ENG:
                                if _cjk:
                                    break
                                _eng.append(part)
                            else:
                                _cjk.append(part)
                        else:
                            lang_sort_worked = True

                        if lang_sort_worked:
                            if _eng and _cjk:
                                name_parts = [' '.join(_eng), ' '.join(_cjk)]
                            else:
                                raise WikiEntityParseException(err_msg) from e
                        else:
                            lc_name = name_parts[0].lower()
                            if section.endswith('OST') and i == 1 and lc_name.endswith(' title'):
                                base = name_parts[0][:-5].strip()
                                if LangCat.categorize(base) in LangCat.asian_cats:
                                    name_parts = [base]
                                    to_include['misc'] = ['Title']
                                else:
                                    name_parts = name_parts[0]  # Let parse_track_info split the string
                            else:
                                name_parts = name_parts[0]  # Let parse_track_info split the string
                elif all(part.lower().endswith('(inst.)') for part in name_parts):
                    name_parts = [part[:-7].strip() for part in name_parts]
                    name_parts.append('Inst.')
                elif len(name_parts) == 2:
                    common_part_suffix = common_suffix(name_parts)
                    if common_part_suffix:
                        unique_parts = [p[:-len(common_part_suffix)].strip() for p in name_parts]
                        name_parts = '{} ({}) {{}}'.format(*unique_parts).format(common_part_suffix)

                track = parse_track_info(tds[0].text, name_parts, uri_path, include=to_include)

                artists_text = tds[2].text.strip()
                if LangCat.contains_any_not(artists_text, LangCat.ENG):
                    page_eng_cjk_artists.add(artists_text)
                else:
                    # Make it easier to match eng+cjk since most pages only include both in the first occurrence
                    for prev_artist in sorted(page_eng_cjk_artists):
                        if prev_artist.startswith(artists_text):
                            remainder = prev_artist[len(artists_text):].strip()
                            if remainder.startswith('(') and remainder.endswith(')'):
                                artists_text = prev_artist
                                break

                track['collaborators'], track['produced_by'] = split_artist_list(
                    artists_text, context=uri_path, anchors=anchors, client=client
                )
                tracks.append(track)

        track_lists.append({'section': section, 'tracks': tracks, 'info': info})
        h2 = h2.find_next_sibling('h2')

    return track_lists


def parse_drama_wiki_info_list(uri_path, info_ul, client):
    info = {}
    for i, li in enumerate(info_ul.find_all('li')):
        if li.parent != info_ul:
            continue
        try:
            key, value = map(str.strip, li.text.strip().split(':', 1))
        except ValueError as e:
            fmt = 'Error splitting key:value pair {!r} from {}: {}'
            raise WikiEntityParseException(fmt.format(li.text.strip(), uri_path, e)) from e

        key = key.lower()
        if i == 0 and key not in ('title', 'name', 'group name'):
            return None
        elif key in ('title', 'name', 'group name'):
            parts = list(map(str.strip, value.split('/')))
            try:
                value = eng_cjk_sort(parts, permissive=True)
            except Exception as e:
                langs = [LangCat.categorize(p) for p in parts]
                if len(parts) == 3 and langs[0] == LangCat.HAN and langs[1] == langs[2] == LangCat.ENG:
                    permutations = {''.join(p.split()) for p in romanized_permutations(parts[0])}
                    if all(''.join(p.lower().split()) in permutations for p in parts[1:]):
                        value = ('', parts[0])
                elif len(parts) == 2 and all(lang in LangCat.asian_cats for lang in langs):
                    value = ('', parts[0])
                    fmt = 'No english title found for {}; 2 non-eng titles found: {!r} (keeping) / {!r} (discarding)'
                    log.debug(fmt.format(uri_path, *parts))
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
            anchors = tuple(li.find_all('a'))
            value, info['produced_by'] = split_artist_list(value, context=uri_path, anchors=anchors, client=client)
        elif key == 'also known as':
            value = str2list(value)
        elif key in ('original soundtrack', 'original soundtracks'):
            links = dict(link_tuples(li.find_all('a')))
            value = {value: links.get(value)}
        elif key == 'viewership ratings':
            continue

        info[key] = value
    return info
