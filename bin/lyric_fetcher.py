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
from itertools import chain
from urllib.parse import urlsplit

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ds_tools.http import RestClient
from ds_tools.logging import LogManager
from ds_tools.utils import Table, SimpleColumn, validate_or_make_dir, soupify, fix_html_prettify, ArgParser, now

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
    get_parser.add_argument("song", help="Endpoint that contains lyrics for a particular song")
    get_parser.add_argument("--title", "-t", help="Page title to use (default: last part of song endpoint)")
    get_parser.add_argument("--size", "-z", type=int, default=12, help="Font size to use for output")
    get_parser.add_argument("--ignore_len", "-i", action="store_true", help="Ignore stanza length match")

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

    hybrid_parser.add_argument("--english_lb", "-el", nargs="+", help="Additional linebreaks to use to split English stanzas")
    hybrid_parser.add_argument("--korean_lb", "-kl", nargs="+", help="Additional linebreaks to use to split Korean stanzas")

    hybrid_parser.add_argument("--english_extra", "-ex", nargs="+", help="Additional lines to add to the English stanzas at the end")
    hybrid_parser.add_argument("--korean_extra", "-kx", nargs="+", help="Additional lines to add to the Korean stanzas at the end")

    parser.include_common_args("verbosity")
    return parser


def main():
    args = parser().parse_args(req_subparser_value=True)
    LogManager.create_default_logger(args.verbose, log_path=None)

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
            lf.index(args.index, args.album_filter, args.list)
        elif args.action == "get":
            lf.process_lyrics(args.song, args.title, args.size, args.ignore_len)
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
            None, args.title, args.size, args.ignore_len,
            kor_endpoint=args.korean_endpoint, eng_endpoint=args.english_endpoint,
            english_lb=english_lb, korean_lb=korean_lb,
            english_extra=args.english_extra, korean_extra=args.korean_extra
        )
    else:
        raise ValueError("Unconfigured action: {}".format(args.action))


class LyricFetcher(RestClient):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._cache_dir = os.path.join(CACHE_DIR, self.host)
        validate_or_make_dir(self._cache_dir)
        fix_html_prettify()

    def print_search_results(self, *args):
        raise TypeError("print_search_results() is not implemented for {}".format(self.host))

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

    def process_lyrics(self, song, title=None, size=12, ignore_len=False, english_lb=None, korean_lb=None, english_extra=None, korean_extra=None, **kwargs):
        """
        Process lyrics from the given song and write them to an html file

        :param str|None song: Song endpoint for lyrics
        :param str title: Title to use (overrides automatically-extracted title is specified)
        :param int size: Font size to use for output
        :param bool ignore_len: Ignore stanza length mismatches
        :param kwargs: Keyword arguments to pass to :func:`LyricFetcher.get_lyrics`
        """
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

        cache_file = "{}/lyrics_{}.html".format(CACHE_DIR, new_header.text.replace(" ", "_"))
        log.info("Saving lyrics to {}".format(cache_file))
        prettified = html.prettify(formatter="html")
        with open(cache_file, "w", encoding="utf-8") as f:
            f.write(prettified)

    def get(self, endpoint, **kwargs):
        cache_file = "{}/get_{}.html".format(self._cache_dir, endpoint.replace("/", "_"))

        if not kwargs.get("params"):
            if os.path.exists(cache_file):
                with open(cache_file, "r", encoding="utf-8") as f:
                    return f.read()

        resp = super().get(endpoint, **kwargs)

        if not kwargs.get("params"):
            with open(cache_file, "w", encoding="utf-8") as f:
                f.write(resp.text)

        return resp.text

    def search(self, query, query_part_2=None):
        cache_file = "{}/search_{}_{}.html".format(self._cache_dir, now("%Y-%m-%d"), query.replace("/", "_"))
        if os.path.exists(cache_file):
            with open(cache_file, "r", encoding="utf-8") as f:
                return f.read()

        resp = self.get("/", params={"s": query})
        with open(cache_file, "w", encoding="utf-8") as f:
            f.write(resp)

        return resp

    def index(self, query, album_filter=None, list=False):
        raise TypeError("Song index information is not available for {}".format(self.host))


class HybridLyricFetcher(LyricFetcher):
    # noinspection PyMissingConstructor
    def __init__(self, kor_lf, eng_lf):
        self.kor_lf = kor_lf
        self.eng_lf = eng_lf
        self._cache_dir = os.path.join(CACHE_DIR, self.kor_lf.host, self.eng_lf.host)
        validate_or_make_dir(self._cache_dir)
        fix_html_prettify()

    def get_lyrics(self, song=None, title=None, *, kor_endpoint=None, eng_endpoint=None):
        """
        :param str song: Song endpoint for lyrics
        :param str title: Title to use (overrides automatically-extracted title is specified)
        :param str kor_endpoint: Endpoint from which Korean lyrics should be retrieved
        :param str eng_endpoint: Endpoint from which English lyrics should be retrieved
        :return dict: Mapping of {"Korean": list(lyrics), "English": list(lyrics), "title": title}
        """
        kor_lyrics, kor_title = self.kor_lf.get_korean_lyrics(kor_endpoint)
        eng_lyrics, eng_title = self.eng_lf.get_english_translation(eng_endpoint)
        log.debug("Found Korean title: '{}', English title: '{}'".format(kor_title, eng_title))
        return {"Korean": kor_lyrics, "English": eng_lyrics, "title": kor_title or eng_title}


class LyricsTranslateLyricFetcher(LyricFetcher):
    def __init__(self):
        super().__init__("lyricstranslate.com", proto="https")

    def search(self, artist, song=None):
        return self.get("en/translations/0/328/{}/{}/none/0/0/0/0".format(artist, song if song else "none"))

    def print_search_results(self, *args):
        soup = soupify(self.search(*args))
        tbl = Table(SimpleColumn("Link", 0), SimpleColumn("Song", 0), update_width=True)
        results = []
        for row in soup.find("div", class_="ltsearch-results-line").find_all("tr"):
            lang = row.find("td", class_="ltsearch-translatelanguages")
            if lang and ("English" in lang.text):
                a = row.find_all("td", class_="ltsearch-translatenameoriginal")[1].find("a")
                link = a.get("href")
                text = a.get_text()
                results.append({"Song": text, "Link": urlsplit(link).path[1:]})
        tbl.print_rows(results)

    def get_english_translation(self, song):
        html = soupify(self.get(song), "lxml")
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
    def __init__(self):
        super().__init__("klyrics.net", proto="https")

    def print_search_results(self, *args):
        soup = soupify(self.search(*args))
        tbl = Table(SimpleColumn("Link", 0), SimpleColumn("Song", 0), update_width=True)
        results = []
        for post in soup.find_all("h3", class_="entry-title"):
            link = post.find("a").get("href")
            text = post.get_text()
            results.append({"Song": text, "Link": urlsplit(link).path[1:]})
        tbl.print_rows(results)

    def get_lyrics(self, song, title=None, *, kor_endpoint=None, eng_endpoint=None):
        lyrics = {"Korean": [], "English": [], "title": title}
        html = soupify(self.get(song), "lxml")
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

    def index(self, query, album_filter=None, list=False):
        alb_filter = re.compile(album_filter) if album_filter else None
        endpoint = self.indexes.get(re.sub("[\[\]~!@#$%^&*(){}:;<>,.?/\\+= -]", "", query.lower()))
        if not endpoint:
            raise ValueError("No index is configured for {}".format(query))

        soup = soupify(self.get(endpoint))
        for td in soup.find_all("td"):
            tbl = Table(SimpleColumn("Link", 0), SimpleColumn("Song", 0), update_width=True)
            results = []
            img = td.find("img")
            title = img.get("title")

            if alb_filter and (not title or not alb_filter.search(title)):
                continue
            if list:
                print(title)
                continue

            for a in td.find_all("a"):
                link = a.get("href")
                results.append({"Song": a.text, "Link": urlsplit(link).path[1:]})
            print("{}:".format(title))
            try:
                tbl.print_rows(results)
            except Exception as e:
                print("(none)")
            print()

    def print_search_results(self, *args):
        soup = soupify(self.search(*args))
        tbl = Table(SimpleColumn("Link", 0), SimpleColumn("Song", 0), update_width=True)
        results = []
        for post in soup.find_all("h2", class_="entry-title"):
            link = post.find("a").get("href")
            text = post.get_text()
            results.append({"Song": text, "Link": urlsplit(link).path[1:]})
        tbl.print_rows(results)

    def get_lyrics(self, song, title=None, *, kor_endpoint=None, eng_endpoint=None):
        html = soupify(self.get(song), "lxml")
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

    # def process_lyrics(self, song, title=None, size=12):
    #     html = soupify(self.get(song), "lxml")
    #     new_html = soupify(HTML_TEMPLATE.format(size))
    #
    #     new_header = new_html.new_tag("h1")
    #     new_header.string = title or html.find("h1", class_="entry-title").get_text()
    #     new_html.find("body").insert(0, new_header)
    #
    #     lang_names = {1: "Korean", 2: "English"}
    #     stanza_lines = defaultdict(list)
    #     lang_row = html.find("th", text="Romanization").parent.next_sibling.next_sibling
    #     for i, td in enumerate(lang_row.find_all("td")):
    #         if i:   # Skip romanization
    #             td_str = str(td)
    #             td_str = td_str[:4] + "<p>" + td_str[4:]
    #             fixed_td = soupify(re.sub("(?<!</p>|<td>)<p>", "</p><p>", td_str))
    #
    #             log.log(5, "Fixed td:\n{}\n\n".format(fixed_td))
    #
    #             for p in fixed_td.find_all("p"):
    #                 lines = [l for l in p.get_text().replace("<br/>", "\n").splitlines() if l]
    #                 for j, line in enumerate(lines):
    #                     if line.startswith("<span"):
    #                         lines[j] = soupify(line).find("span").get_text()
    #                 log.log(9, "{}: found stanza with {} lines".format(lang_names[i], len(lines)))
    #
    #                 # lines = [l for span in p.find_all("span") for l in span.get_text().replace("<br/>", "\n").splitlines() if l]
    #                 # if not lines:
    #                 #     lines = [l for l in p.get_text().replace("<br/>", "\n").splitlines() if l]
    #                 #     log.log(9, "{}: found stanza with {} plain lines".format(lang_names[i], len(lines)))
    #                 # else:
    #                 #     log.log(9, "{}: found stanza with {} span lines".format(lang_names[i], len(lines)))
    #
    #                 lines.append("<br/>")
    #                 stanza_lines[i].extend(lines)
    #
    #     tbody = new_html.find("tbody")
    #     langs = sorted(stanza_lines.keys())
    #
    #     for n in range(len(stanza_lines[1])):
    #         new_row = new_html.new_tag("tr")
    #         for lang in langs:
    #             line = stanza_lines[lang][n]
    #             td = new_html.new_tag("td")
    #             td.append(line if line != "<br/>" else new_html.new_tag("br"))
    #             new_row.append(td)
    #
    #         tbody.append(new_row)
    #
    #     cache_file = "{}/lyrics_{}.html".format(CACHE_DIR, new_header.text.replace(" ", "_"))
    #     log.info("Saving lyrics to {}".format(cache_file))
    #     prettified = new_html.prettify(formatter="html")
    #     with open(cache_file, "w", encoding="utf-8") as f:
    #         f.write(prettified)


SITE_CLASS_MAPPING = {
    "colorcodedlyrics": ColorCodedLyricFetcher,
    "klyrics": KlyricsLyricFetcher,
    "lyricstranslate": LyricsTranslateLyricFetcher,
}


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print()
