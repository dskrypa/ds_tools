"""
:author: Doug Skrypa
"""

import logging
from collections import OrderedDict

from ....unicode import LangCat
from ....utils import DASH_CHARS, QMARKS, ListBasedRecursiveDescentParser, ALL_WHITESPACE, UnexpectedTokenError
from ...name_processing import categorize_langs, combine_name_parts, eng_cjk_sort, str2list
from .exceptions import *

__all__ = [
    'album_num_type', 'first_side_info_val', 'LANG_ABBREV_MAP', 'link_tuples', 'NUM2INT', 'parse_track_info',
    'TrackInfoParser', 'unsurround'
]
log = logging.getLogger(__name__)

FEAT_ARTIST_INDICATORS = ('with', 'feat.', 'feat ', 'featuring')
LANG_ABBREV_MAP = {
    'chinese': 'Chinese', 'chn': 'Chinese',
    'english': 'English', 'en': 'English', 'eng': 'English',
    'japanese': 'Japanese', 'jp': 'Japanese', 'jap': 'Japanese', 'jpn': 'Japanese',
    'korean': 'Korean', 'kr': 'Korean', 'kor': 'Korean', 'ko': 'Korean',
    'spanish': 'Spanish'
}
NUM2INT = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9}
NUMS = {
    'first': '1st', 'second': '2nd', 'third': '3rd', 'fourth': '4th', 'fifth': '5th', 'sixth': '6th',
    'seventh': '7th', 'eighth': '8th', 'ninth': '9th', 'tenth': '10th', 'debut': '1st'
}


class TrackInfoParser(ListBasedRecursiveDescentParser):
    _entry_point = 'content'
    _strip = True
    _opener2closer = {'LPAREN': 'RPAREN', 'LBPAREN': 'RBPAREN', 'LBRKT': 'RBRKT', 'QUOTE': 'QUOTE', 'DASH': 'DASH'}
    _nested_fmts = {'LPAREN': '({})', 'LBPAREN': '({})', 'LBRKT': '[{}]', 'QUOTE': '{!r}', 'DASH': '({})'}
    _content_tokens = ['TEXT', 'WS'] + [v for k, v in _opener2closer.items() if k != v]
    _req_preceders = ['WS'] + list(_opener2closer.values())
    TOKENS = OrderedDict([
        ('QUOTE', '[{}]'.format(QMARKS)),
        ('LPAREN', '\('),
        ('RPAREN', '\)'),
        ('LBPAREN', '（'),
        ('RBPAREN', '）'),
        ('LBRKT', '\['),
        ('RBRKT', '\]'),
        ('TIME', '\s*\d+:\d{2}'),
        ('WS', '\s+'),
        ('DASH', '[{}]'.format(DASH_CHARS)),
        ("TEXT", "[^{}{}()（）\[\]{}]+".format(DASH_CHARS, QMARKS, ALL_WHITESPACE)),
    ])

    def __init__(self, selective_recombine=True):
        self._selective_recombine = selective_recombine

    def parse(self, text, context=None):
        self._context = context
        return super().parse(text)

    def _lookahead_unpaired(self, closer):
        """Find the position of the next closer that does not have a preceding opener in the remaining tokens"""
        openers = {opener for opener, _closer in self._opener2closer.items() if _closer == closer}
        opened = 0
        closed = 0
        # log.debug("Looking for next {!r} from idx={} in {}".format(closer, self._idx, self.tokens))
        for pos, token in self.tokens[self._idx:]:
            if token.type == closer:
                closed += 1
                if closed > opened:
                    return pos
            elif token.type in openers:
                opened += 1
        return -1

    def parenthetical(self, closer='RPAREN'):
        """
        parenthetical ::= ( { text | WS | ( parenthetical ) }* )
        """
        # log.debug('Opening {}'.format(closer))
        self._parenthetical_count += 1
        text = ''
        parts = []
        nested = False
        while self.next_tok:
            if self._accept(closer):
                if text:
                    parts.append(text)
                # log.debug('[closing] Closing {}: {}'.format(closer, parts))
                return parts, nested, False
            elif self._accept_any(self._opener2closer):
                prev_tok_type = self.prev_tok.type
                tok_type = self.tok.type
                if tok_type == 'DASH':
                    # next_dash = self._lookahead('DASH')
                    try:
                        next_dash = self._remaining.index(self.tok.value) + self._pos
                    except ValueError:
                        next_dash = -1
                    next_closer = self._lookahead_unpaired(closer)
                    # log.debug('Found DASH @ pos={}, next is @ pos={}; closer pos={}'.format(self._pos, next_dash, next_closer))
                    if next_dash == -1 or next_dash > next_closer:
                        text += self.tok.value
                        continue
                    elif text and not prev_tok_type == 'WS' and self._peek('TEXT'):
                        text += self.tok.value
                        continue

                if text:
                    parts.append(text)
                    text = ''

                parentheticals, _nested, unpaired = self.parenthetical(self._opener2closer[tok_type])
                if len(parts) == len(parentheticals) == 1 and self._parenthetical_count > 2:
                    if parts[0].lower().startswith(FEAT_ARTIST_INDICATORS):
                        parts[0] = '{} of {}'.format(parts[0].strip(), parentheticals[0])
                    elif parentheticals[0].lower().endswith((' ver.', ' ver', ' version', ' edition', ' ed.')):
                        parts.extend(parentheticals)
                    else:
                        parts[0] += self._nested_fmts[tok_type].format(parentheticals[0])
                else:
                    parts.extend(parentheticals)

                nested = True
            else:
                self._advance()
                text += self.tok.value

        if text:
            parts.append(text)
        # log.debug('[no toks] Closing {}: {}'.format(closer, parts))
        return parts, nested, True

    def content(self):
        """
        content :: = text { (parenthetical) }* { text }*
        """
        self._parenthetical_count = 0
        text = ''
        time_part = None
        parts = []
        while self.next_tok:
            if self._accept_any(self._opener2closer):
                tok_type = self.tok.type
                if text and self.prev_tok.type not in self._req_preceders and self._peek('TEXT'):
                    text += self.tok.value
                    continue
                elif tok_type == 'QUOTE':
                    if any((c not in self._remaining) and (self._full.count(c) % 2 == 1) for c in QMARKS):
                        log.debug('Unpaired quote found in {!r} - {!r}'.format(self._context, self._full))
                        continue
                elif tok_type == 'DASH':
                    # log.debug('Found DASH ({!r}={}); remaining: {!r}'.format(self.tok.value, ord(self.tok.value), self._remaining))
                    if self._peek('TIME'):
                        if text:
                            parts.append(text)
                            text = ''
                        continue
                    elif self._peek('WS') or self.tok.value not in self._remaining:
                        # log.debug('Appending DASH because WS did not follow it or the value does not occur again')
                        text += self.tok.value
                        continue

                if text:
                    parts.append(text)
                    text = ''
                parentheticals, nested, unpaired = self.parenthetical(self._opener2closer[tok_type])
                # log.debug('content parentheticals: {}'.format(parentheticals))
                # log.debug('Parsed {!r} (nested={}); next token={!r}'.format(parentheticals, nested, self.next_tok))
                if not nested and not self._peek('WS') and self.next_tok is not None and len(parentheticals) == 1:
                    text += self._nested_fmts[tok_type].format(parentheticals[0])
                elif len(parentheticals) == 1 and isinstance(parentheticals[0], str):
                    parts.append((parentheticals[0], nested, tok_type))
                else:
                    parts.extend(parentheticals)
            elif self._accept_any(self._content_tokens):
                text += self.tok.value
            elif self._accept('TIME'):
                if self.prev_tok.type == 'DASH' or not self.next_tok:
                    if time_part:
                        fmt = 'Unexpected {!r} token {!r} in {!r} (time {!r} was already found)'
                        raise UnexpectedTokenError(fmt.format(
                            self.next_tok.type, self.next_tok.value, self._full, time_part
                        ))
                    time_part = self.tok.value.strip()
                else:
                    text += self.tok.value
            else:
                raise UnexpectedTokenError('Unexpected {!r} token {!r} in {!r}'.format(
                    self.next_tok.type, self.next_tok.value, self._full
                ))

        if text:
            parts.append(text)

        if self._selective_recombine:
            single_idxs = set()
            had_nested = False
            for i, part in enumerate(parts):
                if isinstance(part, tuple):
                    nested = part[1]
                    had_nested = had_nested or nested
                    if not nested:
                        single_idxs.add(i)

            # log.debug('{!r} => {} [nested: {}][singles: {}]'.format(self._full, parts, had_nested, sorted(single_idxs)))
            if had_nested and single_idxs:
                single_idxs = sorted(single_idxs)
                while single_idxs:
                    i = single_idxs.pop(0)
                    for ti in (i - 1, i + 1):
                        if (ti < 0) or (ti > (len(parts) - 1)):
                            continue
                        if isinstance(parts[ti], str) and parts[ti].strip():
                            parenthetical, nested, tok_type = parts[i]
                            formatted = self._nested_fmts[tok_type].format(parenthetical)
                            parts[ti] = (formatted + parts[ti]) if ti > i else (parts[ti] + formatted)
                            parts.pop(i)
                            single_idxs = [idx - 1 for idx in single_idxs]
                            break

        cleaned = (part for part in map(str.strip, (p[0] if isinstance(p, tuple) else p for p in parts)) if part)
        return [part for part in cleaned if part not in '"“()（）[]'], time_part


def unsurround(a_str, *chars):
    chars = chars or (('"', '"'), ('(', ')'), ('“', '“'))
    for a, b in chars:
        if a_str.startswith(a) and a_str.endswith(b):
            a_str = a_str[1:-1].strip()
    return a_str


def first_side_info_val(side_info, key):
    try:
        return side_info.get(key, [])[0][0]
    except IndexError:
        return None


def link_tuples(anchors):
    tuple_gen = ((a.text, a.get('href') or '') for a in anchors)
    return [(text, href[6:] if href.startswith('/wiki/') else href) for text, href in tuple_gen if href]


def album_num_type(details):
    alb_broad_type = next((val for val in ('album', 'single') if val in details), None)
    if alb_broad_type:
        alb_type_desc = details[:details.index(alb_broad_type) + 1]
        if 'full-length' in alb_type_desc:
            alb_type_desc.remove('full-length')
        num = NUMS.get(alb_type_desc[0])
        return num, ' '.join(alb_type_desc[1:] if num else alb_type_desc)
    elif len(details) > 1 and details[0] == 'song' and details[1] == 'by':
        return None, 'single'
    raise ValueError('Unable to determine album type from details: {}'.format(details))


def parse_track_info(idx, text, source, length=None, *, include=None, links=None, compilation=False):
    """
    Split and categorize the given text to identify track metadata such as length, collaborators, and english/cjk name
    parts.

    :param int|str idx: Track number / index in list (1-based)
    :param str|container text: The text to be parsed, or already parsed/split text
    :param str source: uri_path or other identifier for the source of the text being parsed (to add context to errors)
    :param str|None length: Length of the track, if known (MM:SS format)
    :param dict|None include: Additional fields to be included in the returned track dict
    :param list|None links: List of tuples of (text, href) that were in the html for the given text
    :return dict: The parsed track information
    """
    if isinstance(idx, str):
        idx = idx.strip()
        if idx.endswith('.'):
            idx = idx[:-1]
        try:
            idx = int(idx)
        except ValueError as e:
            fmt = 'Error parsing track number {!r} for {!r} from {}: {}'
            raise TrackInfoParseException(fmt.format(idx, text, source, e)) from e

    track = {'num': idx, 'length': '-1:00'}
    if include:
        track.update(include)
    if isinstance(text, str):
        text = unsurround(text.strip(), *(c*2 for c in QMARKS))
        try:
            parsed, time_part = TrackInfoParser().parse(text, source)
        except Exception as e:
            raise TrackInfoParseException('Error parsing track from {}: {!r}'.format(source, text)) from e
    else:
        parsed = text
        time_part = None

    # log.debug('{!r} => {}'.format(text, parsed))
    if length:
        track['length'] = length
    if time_part:
        if length:
            fmt = 'Length={!r} was provided for track {}/{!r} from {}, but it was also parsed to be {!r}'
            raise TrackInfoParseException(fmt.format(length, idx, text, source, time_part))
        track['length'] = time_part

    try:
        version_types = parse_track_info._version_types
        misc_indicators = parse_track_info._misc_indicators
    except AttributeError:
        version_types = parse_track_info._version_types = (
            'inst', 'acoustic', 'ballad', 'original', 'remix', 'r&b', 'band', 'karaoke', 'special', 'full length',
            'single', 'album', 'radio', 'limited', 'normal', 'english rap', 'rap', 'piano', 'acapella', 'edm', 'stage',
            'live', 'rock', 'director\'s'
        )
        misc_indicators = parse_track_info._misc_indicators = ( # spaces intentional
            'bonus', ' ost', ' mix', 'remix', 'special track', 'prod. by', 'produced by', 'director\'s', ' only',
            'remaster', 'intro', 'unit', 'hidden track'
        )

    name_parts, name_langs, collabs, misc, unknown = [], [], [], [], []
    link_texts = set(link[0] for link in links) if links else None
    if compilation:
        collabs.extend(str2list(parsed.pop(-1), pat='(?: and |,|;|&| feat\.? | featuring | with )'))
        track['compilation'] = True

    for n, part in enumerate(parsed):
        if n == 0:
            # log.debug('{!r}: Adding to name parts: {!r}'.format(text, part))
            name_parts.append(part)
            name_langs.append(LangCat.categorize(part))
            continue
        elif not part:
            continue

        lc_part = part.lower()
        feat = next((val for val in FEAT_ARTIST_INDICATORS if val in lc_part), None)
        duet_etc = next((val for val in (' duet', ' trio') if val in lc_part), None)
        if feat:
            collab_part = part[len(feat):].strip() if lc_part.startswith(feat) else part
            collabs.extend(str2list(collab_part, pat='(?: and |,|;|&| feat\.? | featuring | with )'))
            # collabs.extend(str2list(part[len(feat):].strip()))
        elif duet_etc:
            collab_part = part[:-len(duet_etc)].strip()
            collabs.extend(str2list(collab_part, pat='(?: and |,|;|&| feat\.? | featuring | with )'))
        elif lc_part.endswith(' solo'):
            track['artist'] = part[:-5].strip()
        elif lc_part.endswith((' ver.', ' ver', ' version', ' edition', ' ed.')):
            value = part.rsplit(maxsplit=1)[0]
            if lc_part.startswith(version_types):
                if track.get('version'):
                    if track['version'].lower() == value.lower():
                        continue
                    log.warning('Multiple version entries found for {!r} from {!r}'.format(text, source), extra={'color': 14})
                    misc.append('{} ver.'.format(value) if 'ver' in lc_part and 'ver' not in value else part)
                else:
                    track['version'] = value
            else:
                try:
                    track['language'] = LANG_ABBREV_MAP[value.lower()]
                except KeyError:
                    log.debug('Found unexpected version text in {!r} - {!r}: {!r}'.format(source, text, value), extra={'color': 100})
                    if track.get('version'):
                        old_ver = track['version']
                        if old_ver.lower() == value.lower():
                            continue

                        new_ver = '{} ver.'.format(value) if 'ver' in lc_part and 'ver' not in value else part
                        if len(set(categorize_langs((old_ver, new_ver)))) == 1:
                            warn_fmt = 'Multiple version entries found for {!r} from {!r}'
                            log.warning(warn_fmt.format(text, source), extra={'color': 14})

                        misc.append(new_ver)
                    else:
                        track['version'] = value
        elif lc_part.startswith(('inst', 'acoustic')):
            if track.get('version'):
                lc_version = track['version'].lower()
                if any(val in lc_version for val in ('inst', 'acoustic')):
                    log.warning('Multiple version entries found for {!r} from {!r}'.format(text, source), extra={'color': 14})
                misc.append('{} ver.'.format(track['version']) if 'ver' not in track['version'].lower() else part)
            track['version'] = part
        elif any(val in lc_part for val in misc_indicators) or all(val in lc_part for val in (' by ', ' of ')):
            misc.append(part)
        elif links and any(link_text in part for link_text in link_texts):
            split_part = str2list(part, pat='(?: and |,|;|&| feat\.? | featuring | with )')
            if any(sp in link_texts for sp in split_part):
                collabs.extend(split_part)                  # assume links are to artists
            elif len(set(name_langs)) < 2:
                # log.debug('{!r}: Adding to name parts: {!r}'.format(text, part))
                name_parts.append(part)
                name_langs.append(LangCat.categorize(part))
            else:
                log.debug('Assuming {!r} from {!r} > {!r} is misc [no link matches]'.format(part, source, text), extra={'color': 70})
                misc.append(part)
        else:
            if len(set(name_langs)) < 2:
                # log.debug('{!r}: Adding to name parts: {!r}'.format(text, part))
                name_parts.append(part)
                name_langs.append(LangCat.categorize(part))
            else:
                log.debug('Assuming {!r} from {!r} > {!r} is misc'.format(part, source, text), extra={'color': 70})
                misc.append(part)

    if len(name_parts) > 2:
        log.log(9, 'High name part count in {} [{!r} =>]: {}'.format(source, text, name_parts))
        while len(name_parts) > 2:
            name_parts = combine_name_parts(name_parts)

    try:
        track['name_parts'] = eng_cjk_sort(name_parts[0] if len(name_parts) == 1 else name_parts, tuple(name_langs))
    except ValueError:
        track['name_parts'] = tuple(name_parts) if len(name_parts) == 2 else (name_parts[0], '')

    if collabs:
        track['collaborators'] = sorted(collabs)
    if misc:
        track['misc'] = misc
    if unknown:
        track['unknown'] = unknown

    return track
