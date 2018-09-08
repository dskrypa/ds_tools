#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Fetch Korean lyrics and fix the html to make them easier to print

:author: Doug Skrypa
"""

import logging
import os
import re
import sys
from collections import OrderedDict
from itertools import chain
from urllib.parse import urlsplit

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ds_tools.http import RestClient
from ds_tools.logging import LogManager
from ds_tools.utils import (
    Table, SimpleColumn, validate_or_make_dir, soupify, fix_html_prettify, ArgParser, FSCache, cached,
    get_user_cache_dir, rate_limited
)

log = logging.getLogger("ds_tools.{}".format(__name__))

DEFAULT_SITE = "colorcodedlyrics"
CACHE_DIR = "/var/tmp/script_cache"
TIDY_PATH = "C:/unix/home/user/lib/tidy-5.6.0-vc14-64b/bin/tidy.dll"
HTML_TEMPLATE = """<html>
<head>
    <meta http-equiv="content-type" content="text/html; charset=UTF-8">
    <meta charset="UTF-8">
    <style type="text/css">
    * {{font-family: sans-serif;}}
    h1 {{text-align: center;}}
    /*table {{margin: auto;}}*/
    td {{padding: 0px 20px 0px 20px; font-size: {}pt;}}
    th {{margin: auto; text-align: center;}}
    </style>
</head>
<body>
    <table>
        <tbody>
            <tr>
                <th>Korean</th>
                <th>Translation</th>
            </tr>
        </tbody>
    </table>
</body>
</html>
"""


def parser():
    site_names = sorted(SITE_CLASS_MAPPING.keys())
    parser = ArgParser(description="Lyric Fetcher")

    list_parser = parser.add_subparser("action", "list", "List available sites")

    get_parser = parser.add_subparser("action", "get", "Retrieve lyrics from a particular page from a single site")
    get_parser.add_argument("song", nargs="+", help="One or more endpoints that contain lyrics for particular songs")
    get_parser.add_argument("--title", "-t", help="Page title to use (default: extracted from lyric page)")
    get_parser.add_argument("--size", "-z", type=int, default=12, help="Font size to use for output")
    get_parser.add_argument("--ignore_len", "-i", action="store_true", help="Ignore stanza length match")
    get_parser.add_argument("--output", "-o", help="Output directory to store the lyrics")

    search_parser = parser.add_subparser("action", "search", "Search for lyric pages")
    search_parser.add_argument("query", help="Query to run")
    search_parser.add_argument("--sub_query", "-q", help="Sub-query to run")

    index_parser = parser.add_subparser("action", "index", "View lyric page endpoints from an artist's index page")
    index_parser.add_argument("index", help="Name of the index to view")
    index_parser.add_argument("--album_filter", "-af", help="Filter for albums to be displayed")
    index_parser.add_argument("--list", "-L", action="store_true", help="List albums instead of song links (default: %(default)s)")

    for _parser in (get_parser, search_parser, index_parser):
        _parser.add_argument("--site", "-s", choices=site_names, default=DEFAULT_SITE, help="Site to use (default: %(default)s)")

    hybrid_parser = parser.add_subparser("action", "hybrid_get", "Retrieve lyrics from two separate sites and merge them")
    hybrid_parser.add_argument("--korean_site", "-ks", choices=site_names, help="Site from which Korean lyrics should be retrieved", required=True)
    hybrid_parser.add_argument("--english_site", "-es", choices=site_names, help="Site from which the English translation should be retrieved", required=True)
    hybrid_parser.add_argument("--korean_endpoint", "-ke", help="Site from which Korean lyrics should be retrieved", required=True)
    hybrid_parser.add_argument("--english_endpoint", "-ee", help="Site from which the English translation should be retrieved", required=True)

    hybrid_parser.add_argument("--title", "-t", help="Page title to use (default: last part of song endpoint)")
    hybrid_parser.add_argument("--size", "-z", type=int, default=12, help="Font size to use for output")
    hybrid_parser.add_argument("--ignore_len", "-i", action="store_true", help="Ignore stanza length match")
    hybrid_parser.add_argument("--output", "-o", help="Output directory to store the lyrics")

    hybrid_parser.add_argument("--english_lb", "-el", nargs="+", help="Additional linebreaks to use to split English stanzas")
    hybrid_parser.add_argument("--korean_lb", "-kl", nargs="+", help="Additional linebreaks to use to split Korean stanzas")

    hybrid_parser.add_argument("--english_extra", "-ex", nargs="+", help="Additional lines to add to the English stanzas at the end")
    hybrid_parser.add_argument("--korean_extra", "-kx", nargs="+", help="Additional lines to add to the Korean stanzas at the end")

    file_parser = parser.add_subparser("action", "file_get", "Retrieve lyrics from two separate text files and merge them")
    file_parser.add_argument("--korean", "-k", metavar="PATH", help="Path to a text file containing Korean lyrics")
    file_parser.add_argument("--english", "-e", metavar="PATH", help="Path to a text file containing the English translation")
    file_parser.add_argument("--title", "-t", help="Page title to use", required=True)
    file_parser.add_argument("--size", "-z", type=int, default=12, help="Font size to use for output")
    file_parser.add_argument("--output", "-o", help="Output directory to store the processed lyrics")

    parser.include_common_args("verbosity")
    return parser


def main():
    args = parser().parse_args(req_subparser_value=True)
    LogManager.create_default_logger(args.verbose, log_path=None)

    if args.action == "file_get":
        args.action = "hybrid_get"
        args.korean_site = "file"
        args.english_site = "file"
        args.korean_endpoint = args.korean
        args.english_endpoint = args.english

    if args.action == "list":
        for site in sorted(SITE_CLASS_MAPPING.keys()):
            print(site)
    elif args.action in ("get", "search", "index"):
        try:
            lf = SITE_CLASS_MAPPING[args.site]()
        except KeyError as e:
            raise ValueError("Unconfigured site: {}".format(args.site)) from e

        if args.action == "search":
            lf.print_search_results(args.query, args.sub_query)
        elif args.action == "index":
            lf.print_index_results(args.index, args.album_filter, args.list)
        elif args.action == "get":
            for song in args.song:
                lf.process_lyrics(song, args.title, args.size, args.ignore_len, args.output)
        else:
            raise ValueError("Unconfigured action: {}".format(args.action))
    elif args.action == "hybrid_get":
        fetchers = {}
        for lang in ("korean", "english"):
            site = getattr(args, lang + "_site")
            try:
                fetchers[lang] = SITE_CLASS_MAPPING[site]()
            except KeyError as e:
                raise ValueError("Unconfigured site for {} lyrics: {}".format(lang.title(), site)) from e

        hlf = HybridLyricFetcher(fetchers["korean"], fetchers["english"])

        english_lb = {int(str(val).strip()) for val in args.english_lb or []}
        korean_lb = {int(str(val).strip()) for val in args.korean_lb or []}
        hlf.process_lyrics(
            None, args.title, args.size, args.ignore_len, args.output,
            kor_endpoint=args.korean_endpoint, eng_endpoint=args.english_endpoint,
            english_lb=english_lb, korean_lb=korean_lb,
            english_extra=args.english_extra, korean_extra=args.korean_extra
        )
    else:
        raise ValueError("Unconfigured action: {}".format(args.action))


class LyricFetcher(RestClient):
    _search_result_tag = None
    _search_result_class = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        fix_html_prettify()

    def _format_index(self, query):
        raise TypeError("get_index() is not implemented for {}".format(self.host))

    def get_index_results(self, *args, **kwargs):
        raise TypeError("get_index_results() is not implemented for {}".format(self.host))

    def get_search_results(self, *args, **kwargs):
        if any(val is None for val in (self._search_result_tag, self._search_result_class)):
            raise TypeError("get_search_results() is not implemented for {}".format(self.host))

        soup = self.search(*args, **kwargs)
        results = []
        for post in soup.find_all(self._search_result_tag, class_=self._search_result_class):
            link = post.find("a").get("href")
            text = post.get_text()
            results.append({"Song": text, "Link": urlsplit(link).path[1:]})
        return results

    def print_search_results(self, *args):
        results = self.get_search_results(*args)
        tbl = Table(SimpleColumn("Link"), SimpleColumn("Song"), update_width=True)
        tbl.print_rows(results)

    def print_index_results(self, query, album_filter=None, list_albums=False):
        alb_filter = re.compile(album_filter) if album_filter else None
        results = self.get_index_results(query)
        filtered = [r for r in results if r["Album"] and alb_filter.search(r["Album"])] if alb_filter else results
        if list_albums:
            albums = {r["Album"] for r in filtered if r["Album"]}
            for album in sorted(albums):
                print(album)
        else:
            tbl = Table(SimpleColumn("Album"), SimpleColumn("Link"), SimpleColumn("Song"), update_width=True)
            tbl.print_rows(filtered)

    def get_lyrics(self, song, title=None, *, kor_endpoint=None, eng_endpoint=None):
        """
        :param str|None song: Song endpoint for lyrics
        :param str title: Title to use (overrides automatically-extracted title is specified)
        :param str kor_endpoint: Endpoint from which Korean lyrics should be retrieved
        :param str eng_endpoint: Endpoint from which English lyrics should be retrieved
        :return dict: Mapping of {"Korean": list(lyrics), "English": list(lyrics), "title": title}
        """
        raise TypeError("get_lyrics() is not implemented for {}".format(self.host))

    def get_korean_lyrics(self, song):
        lyrics = self.get_lyrics(song)
        return lyrics["Korean"], lyrics["title"]

    def get_english_translation(self, song):
        lyrics = self.get_lyrics(song)
        return lyrics["English"], lyrics["title"]

    def process_lyrics(self, song, title=None, size=12, ignore_len=False, output_dir=None, english_lb=None, korean_lb=None, english_extra=None, korean_extra=None, **kwargs):
        """
        Process lyrics from the given song and write them to an html file

        :param str|None song: Song endpoint for lyrics
        :param str title: Title to use (overrides automatically-extracted title is specified)
        :param int size: Font size to use for output
        :param bool ignore_len: Ignore stanza length mismatches
        :param kwargs: Keyword arguments to pass to :func:`LyricFetcher.get_lyrics`
        """
        if output_dir and (os.path.exists(output_dir) and not os.path.isdir(output_dir)):
            raise ValueError("Invalid output dir - it exists but is not a directory: {}".format(output_dir))

        lyrics = self.get_lyrics(song, title, **kwargs)

        linebreaks = {
            "English": set(english_lb) if english_lb else set(),
            "Korean": set(korean_lb) if korean_lb else set()
        }
        extras = {"English": english_extra or [], "Korean": korean_extra or []}
        # for lang in ("Korean", "English"):
        #     lang_lyrics = lyrics[lang]
        #     log.log(19, "Language: {}".format(lang))
        #     for i, line in enumerate(lang_lyrics):
        #         log.log(19, "{:3>d} {}".format(i, line))

        stanzas = {"Korean": [], "English": []}
        for lang in ("Korean", "English"):
            lb_set = linebreaks[lang]
            lang_lyrics = lyrics[lang]
            lyric_len = len(lang_lyrics)

            for lb in list(lb_set):
                if lb < 0:
                    lb_set.add(lyric_len + lb)

            stanza = []
            for i, line in enumerate(chain(lang_lyrics, extras[lang])):
                if (line == "<br/>") or (i in lb_set):
                    stanzas[lang].append(stanza)
                    stanza = []
                else:
                    stanza.append(line)

            if stanza:
                stanzas[lang].append(stanza)

        korean_len = len(stanzas["Korean"])
        english_len = len(stanzas["English"])
        if korean_len != english_len:
            for lang in ("Korean", "English"):
                log.log(19, "{}:".format(lang))
                for line in lyrics[lang]:
                    log.log(19, line)
                log.log(19, "")

            msg = "Translation stanzas ({}) don't match original stanzas ({})".format(korean_len, english_len)
            if ignore_len:
                log.warning(msg)
            else:
                raise ValueError(msg)

        html = soupify(HTML_TEMPLATE.format(size))

        new_header = html.new_tag("h1")
        new_header.string = title or lyrics.get("title") or song

        html.find("body").insert(0, new_header)
        tbody = html.find("tbody")

        for n in range(korean_len):
            stanza_row = html.new_tag("tr")
            for lang in ("Korean", "English"):
                lang_td = html.new_tag("td")
                lang_tbl = html.new_tag("table")
                lang_tbody = html.new_tag("tbody")
                lang_tbl.append(lang_tbody)

                for line in stanzas[lang][n]:
                    row = html.new_tag("tr")
                    td = html.new_tag("td")
                    td.append(line)
                    row.append(td)
                    lang_tbody.append(row)

                lang_td.append(lang_tbl)
                stanza_row.append(lang_td)

            tbody.append(stanza_row)

            row = html.new_tag("tr")
            td = html.new_tag("td")
            td.append(html.new_tag("br"))
            row.append(td)
            td = html.new_tag("td")
            td.append(html.new_tag("br"))
            row.append(td)
            tbody.append(row)

        output_dir = output_dir or get_user_cache_dir("lyric_fetcher/lyrics")
        validate_or_make_dir(output_dir)
        output_filename = "lyrics_{}.html".format(new_header.text.replace(" ", "_").replace("?", ""))
        output_path = os.path.join(output_dir, output_filename)
        log.info("Saving lyrics to {}".format(output_path))
        prettified = html.prettify(formatter="html")
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(prettified)

    @rate_limited(1)
    def get(self, *args, **kwargs):
        return super().get(*args, **kwargs)

    @cached(FSCache(cache_subdir="lyric_fetcher", prefix="get__", ext="html"), lock=True, key=FSCache.html_key)
    def get_page(self, endpoint, **kwargs):
        return self.get(endpoint, **kwargs).text

    @cached(FSCache(cache_subdir="lyric_fetcher", prefix="search__", ext="html"), lock=True, key=FSCache.dated_html_key)
    def _search(self, query_0, query_1=None):
        return self.get("/", params={"s": query_0}).text

    @cached(FSCache(cache_subdir="lyric_fetcher", prefix="index__", ext="html"), lock=True, key=FSCache.dated_html_key)
    def _index(self, endpoint, **kwargs):
        return self.get(self._format_index(endpoint), **kwargs).text

    def search(self, *args, **kwargs):
        return soupify(self._search(*args, **kwargs))

    def get_index(self, *args, **kwargs):
        return soupify(self._index(*args, **kwargs))


class HybridLyricFetcher(LyricFetcher):
    # noinspection PyMissingConstructor
    def __init__(self, kor_lf, eng_lf):
        self.kor_lf = kor_lf
        self.eng_lf = eng_lf
        fix_html_prettify()

    def get_lyrics(self, song=None, title=None, *, kor_endpoint=None, eng_endpoint=None):
        """
        :param str song: Song endpoint for lyrics
        :param str title: Title to use (overrides automatically-extracted title if specified)
        :param str kor_endpoint: Endpoint from which Korean lyrics should be retrieved
        :param str eng_endpoint: Endpoint from which English lyrics should be retrieved
        :return dict: Mapping of {"Korean": list(lyrics), "English": list(lyrics), "title": title}
        """
        kor_lyrics, kor_title = self.kor_lf.get_korean_lyrics(kor_endpoint)
        eng_lyrics, eng_title = self.eng_lf.get_english_translation(eng_endpoint)
        log.debug("Found Korean title: '{}', English title: '{}'".format(kor_title, eng_title))
        return {"Korean": kor_lyrics, "English": eng_lyrics, "title": title or kor_title or eng_title}


class TextFileLyricFetcher(LyricFetcher):
    # noinspection PyMissingConstructor
    def __init__(self):
        super().__init__(None)

    def get_lyrics(self, file_path, title=None, **kwargs):
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read().splitlines()

        lines = [line.strip() or "<br/>" for line in content]
        return {"Korean": lines, "English": lines, "title": title}


class LyricsTranslateLyricFetcher(LyricFetcher):
    def __init__(self):
        super().__init__("lyricstranslate.com", proto="https")

    @cached(FSCache(cache_subdir="lyric_fetcher", prefix="search__", ext="html"), lock=True, key=FSCache.dated_html_key)
    def _search(self, artist, song=None):
        return self.get("en/translations/0/328/{}/{}/none/0/0/0/0".format(artist, song if song else "none")).text

    def get_search_results(self, *args, **kwargs):
        results = []
        for row in self.search(*args, **kwargs).find("div", class_="ltsearch-results-line").find_all("tr"):
            lang = row.find("td", class_="ltsearch-translatelanguages")
            if lang and ("English" in lang.text):
                a = row.find_all("td", class_="ltsearch-translatenameoriginal")[1].find("a")
                link = a.get("href")
                text = a.get_text()
                results.append({"Song": text, "Link": urlsplit(link).path[1:]})
        return results

    def get_english_translation(self, song):
        html = soupify(self.get_page(song), "lxml")
        artist_ele = html.find("li", class_="song-node-info-artist")
        artist = artist_ele.text.replace("Artist:", "").strip()
        title = html.find("h2", class_="title-h2").text
        full_title = "{} - {}".format(artist, title)

        content = html.find("div", class_="ltf")
        lines = []
        for par in content.find_all("div", class_="par"):
            stanza = par.get_text().splitlines()
            log.log(19, "{}: found stanza with {} lines".format("English", len(stanza)))
            lines.extend(stanza)
            lines.append("<br/>")

        return lines, full_title


class KlyricsLyricFetcher(LyricFetcher):
    _search_result_tag = "h3"
    _search_result_class = "entry-title"

    def __init__(self):
        super().__init__("klyrics.net", proto="https")

    def get_lyrics(self, song, title=None, *, kor_endpoint=None, eng_endpoint=None):
        lyrics = {"Korean": [], "English": [], "title": title}
        html = soupify(self.get_page(song), "lxml")
        content = html.find("div", class_="td-post-content")
        for h2 in content.find_all("h2"):
            if h2.text.endswith("Hangul"):
                lang = "Korean"
                if title is None:
                    lyrics["title"] = re.match("^(.*?)\s+Hangul$", h2.text).group(1)
            elif h2.text.endswith("English Translation"):
                lang = "English"
            else:
                continue

            log.debug("Found {} section".format(lang))

            ele = h2.next_sibling
            while ele.name in (None, "p"):
                log.log(9, "Processing element: <{0}>{1}</{0}>".format(ele.name, ele))
                if ele.name == "p":
                    lines = [l for l in ele.text.replace("<br/>", "\n").splitlines() if l]
                    log.log(19, "{}: found stanza with {} lines".format(lang, len(lines)))
                    lines.append("<br/>")
                    lyrics[lang].extend(lines)
                ele = ele.next_sibling
        return lyrics


class ColorCodedLyricFetcher(LyricFetcher):
    _search_result_tag = "h2"
    _search_result_class = "entry-title"
    indexes = {
        "redvelvet": "2015/03/red-velvet-lyrics-index",
        "gidle": "2018/05/g-dle-lyrics-index",
        "wekimeki": "2017/09/weki-meki-wikimiki-lyrics-index",
        "blackpink": "2017/09/blackpink-beullaegpingkeu-lyrics-index",
        "ioi": "2016/05/ioi-lyrics-index",
        "twice": "2016/04/twice-lyrics-index",
        "mamamoo": "2016/04/mamamoo-lyric-index",
        "gfriend": "2016/02/gfriend-yeojachingu-lyrics-index",
        "2ne1": "2012/02/2ne1_lyrics_index",
        "snsd": "2012/02/snsd_lyrics_index",
        "missa": "2011/11/miss_a_lyrics_index",
        "apink": "2011/11/a_pink_index",
    }

    def __init__(self):
        super().__init__("colorcodedlyrics.com", proto="https")

    def _format_index(self, query):
        endpoint = self.indexes.get(re.sub("[\[\]~!@#$%^&*(){}:;<>,.?/\\+= -]", "", query.lower()))
        if not endpoint:
            raise ValueError("No index is configured for {}".format(query))
        return endpoint

    def get_index_results(self, query):
        results = []
        for td in self.get_index(query).find_all("td"):
            title = td.find("img").get("title")
            for a in td.find_all("a"):
                link = a.get("href")
                results.append({"Album": title, "Song": a.text, "Link": urlsplit(link).path[1:]})
        return results

    def get_lyrics(self, song, title=None, *, kor_endpoint=None, eng_endpoint=None):
        html = soupify(self.get_page(song), "lxml")
        lyrics = {"Korean": [], "English": [], "title": title or html.find("h1", class_="entry-title").get_text()}
        lang_names = {1: "Korean", 2: "English"}

        lang_row = html.find("th", text="Romanization").parent.next_sibling.next_sibling
        for i, td in enumerate(lang_row.find_all("td")):
            if i:   # Skip romanization
                td_str = str(td)
                td_str = td_str[:4] + "<p>" + td_str[4:]
                fixed_td = soupify(re.sub("(?<!</p>|<td>)<p>", "</p><p>", td_str))

                log.log(5, "Fixed td:\n{}\n\n".format(fixed_td))

                for p in fixed_td.find_all("p"):
                    lines = [l for l in p.get_text().replace("<br/>", "\n").splitlines() if l]
                    for j, line in enumerate(lines):
                        if line.startswith("<span"):
                            lines[j] = soupify(line).find("span").get_text()

                    lang = lang_names[i]
                    log.log(9, "{}: found stanza with {} lines".format(lang, len(lines)))
                    lines.append("<br/>")

                    lyrics[lang].extend(lines)

        return lyrics


class MusixMatchLyricFetcher(LyricFetcher):
    def __init__(self):
        super().__init__("musixmatch.com", proto="https")
        self.session.headers.update({
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "Upgrade-Insecure-Requests": "1",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:62.0) Gecko/20100101 Firefox/62.0"
        })

    def _format_index(self, query):
        return "artist/{}/albums".format(query)

    def get_index_results(self, query):
        album_soup = self.get_index(query)
        results = []
        for a in album_soup.find_all("a", href=re.compile("/album/.*")):
            year = a.parent.next_sibling.get_text()
            album = "[{}] {}".format(year, a.get_text())
            link = a.get("href")

            album_page = soupify(self.get_page(link))
            for track_a in album_page.find_all("a", href=re.compile("/lyrics/.*(?<!/edit)$")):
                track_link = track_a.get("href")
                track_name = track_a.find("h2", class_=re.compile(".*title$")).get_text()
                results.append({"Album": album, "Song": track_name, "Link": track_link})

            # print(album, link)
        return results


SITE_CLASS_MAPPING = {
    "colorcodedlyrics": ColorCodedLyricFetcher,
    "klyrics": KlyricsLyricFetcher,
    "lyricstranslate": LyricsTranslateLyricFetcher,
    "file": TextFileLyricFetcher,
    "musixmatch": MusixMatchLyricFetcher,
}


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print()
