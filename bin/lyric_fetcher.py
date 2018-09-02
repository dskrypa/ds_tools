#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Fetch Korean lyrics and fix the html to make them easier to print

:author: Doug Skrypa
"""

import argparse
import logging
import os
import re
import sys
from abc import ABCMeta, abstractmethod
from urllib.parse import urlsplit

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ds_tools.http import RestClient
from ds_tools.logging import LogManager
from ds_tools.utils import Table, SimpleColumn, validate_or_make_dir, soupify, fix_html_prettify

log = logging.getLogger("ds_tools.{}".format(__name__))

DEFAULT_SITE = "colorcodedlyrics"
SITES = ("colorcodedlyrics", "klyrics")
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


def main():
    parser = argparse.ArgumentParser(description="Lyric Fetcher")
    parser.add_argument("action", choices=("get", "search", "hybrid_get", "index"), help="Action to perform")

    parser.add_argument("song", help="colorcodedlyrics.com endpoint")
    parser.add_argument("--title", "-t", help="Page title to use (default: last part of song endpoint)")

    mgroup = parser.add_mutually_exclusive_group()
    mgroup.add_argument("--search", "-s", action="store_true", help="Perform a search instead of a GET")
    mgroup.add_argument("--index", "-i", action="store_true", help="Perform a index search instead of a GET")

    idx_group = parser.add_argument_group("Index Options")
    idx_group.add_argument("--album_filter", "-af", help="[--index/-i only] Filter for albums to be displayed")
    idx_group.add_argument("--list", "-L", action="store_true", help="List albums instead of song links (default: %(default)s)")

    parser.add_argument("--size", "-z", type=int, default=12, help="Font size to use")
    parser.add_argument("--verbose", "-v", action="count", help="Print more verbose log info (may be specified multiple times to increase verbosity)")

    parser.add_argument("--site", "-S", choices=SITES, default=DEFAULT_SITE, help="Site from which lyrics should be retrieved (default: %(default)s)")
    parser.add_argument("--korean", "-k", choices=SITES, help="Site from which Korean lyrics should be retrieved")
    parser.add_argument("--english", "-e", choices=SITES, help="Site from which the English translation should be retrieved")

    args = parser.parse_args()
    LogManager.create_default_logger(args.verbose, log_path=None)

    if args.korean and args.english and ((args.site != DEFAULT_SITE) or ("-S" in sys.argv or "--site" in sys.argv)):
        raise ValueError("You can only provide --site / -S if it is the source of both the Korean lyrics and the English translation")
    elif (args.korean and not args.english) or (args.english and not args.korean):
        raise ValueError("Both --english / -e and --korean / -k are required if one is specified")

    if args.korean and args.english:
        lf = HybridLyricFetcher()
    elif args.site == "colorcodedlyrics":
        lf = ColorCodedLyricFetcher()
    elif args.site == "klyrics":
        lf = KlyricsLyricFetcher()
    else:
        raise ValueError("Unconfigured site: {}".format(args.site))

    if args.search:
        lf.print_search_results(args.song)
    elif args.index:
        lf.index(args.song, args.album_filter, args.list)
    else:
        lf.process_lyrics(args.song, args.title, args.size)


class LyricFetcher(RestClient, metaclass=ABCMeta):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._cache_dir = os.path.join(CACHE_DIR, self.host)
        validate_or_make_dir(self._cache_dir)
        fix_html_prettify()

    @abstractmethod
    def print_search_results(self, query):
        return None

    @abstractmethod
    def get_lyrics(self, song, title=None):
        """
        :param str song: Song endpoint for lyrics
        :return dict: Mapping of {"Korean": list(lyrics), "English": list(lyrics), "title": title}
        """
        return {}

    def get_korean_lyrics(self, song):
        return self.get_lyrics(song)["Korean"]

    def get_english_translation(self, song):
        return self.get_lyrics(song)["English"]

    def process_lyrics(self, song, title=None, size=12):
        lyrics = self.get_lyrics(song)

        stanzas = {"Korean": [], "English": []}
        for lang in ("Korean", "English"):
            stanza = []
            for line in lyrics[lang]:
                if line == "<br/>":
                    stanzas[lang].append(stanza)
                    stanza = []
                else:
                    stanza.append(line)
            if stanza:
                stanzas[lang].append(stanza)

        korean_len = len(stanzas["Korean"])
        english_len = len(stanzas["English"])
        if korean_len != english_len:
            # for lang in ("Korean", "English"):
            #     print("{}:".format(lang))
            #     for line in lyrics[lang]:
            #         print(line)
            #     print()
            raise ValueError("Translation stanzas ({}) don't match original stanzas ({})".format(korean_len, english_len))

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

    def search(self, query):
        cache_file = "{}/search_{}.html".format(self._cache_dir, query.replace("/", "_"))
        if os.path.exists(cache_file):
            with open(cache_file, "r", encoding="utf-8") as f:
                return f.read()

        resp = self.get("/", params={"s": query})
        with open(cache_file, "w", encoding="utf-8") as f:
            f.write(resp)

        return resp


class HybridLyricFetcher(LyricFetcher):
    # noinspection PyMissingConstructor
    def __init__(self, korean_lf, eng_lf):
        self.korean_lf = korean_lf
        self.eng_lf = eng_lf
        self._cache_dir = os.path.join(CACHE_DIR, self.host)
        validate_or_make_dir(self._cache_dir)
        fix_html_prettify()

    def get_lyrics(self, song, title=None):
        """
        :param str song: Song endpoint for lyrics
        :return dict: Mapping of {"Korean": list(lyrics), "English": list(lyrics), "title": title}
        """
        return {"Korean": self.korean_lf.get_korean_lyrics(song), "English": self.eng_lf.get_english_translation(song)}


class LyricsTranslateLyricFetcher(LyricFetcher):
    def __init__(self):
        super().__init__("lyricstranslate.com", proto="https")

    def search(self, artist):
        return self.get("en/translations/0/328/{}/none/none/0/0/0/0".format(artist))

    def print_search_results(self, query):
        soup = soupify(self.search(query))
        tbl = Table(SimpleColumn("Link", 0), SimpleColumn("Song", 0), update_width=True)
        results = []
        for post in soup.find_all("td", class_="ltsearch-translatenameoriginal"):
            link = post.find("a").get("href")
            text = post.get_text()
            results.append({"Song": text, "Link": urlsplit(link).path[1:]})
        tbl.print_rows(results)

    def get_english_translation(self, song):
        return self.get_lyrics(song)["English"]

    # TODO: get_lyrics
    # https://lyricstranslate.com/en/piano-man-piano-man.html
    # TODO: Hybrid source - other for hangul, this for english


class KlyricsLyricFetcher(LyricFetcher):
    def __init__(self):
        super().__init__("klyrics.net", proto="https")

    def print_search_results(self, query):
        soup = soupify(self.search(query))
        tbl = Table(SimpleColumn("Link", 0), SimpleColumn("Song", 0), update_width=True)
        results = []
        for post in soup.find_all("h3", class_="entry-title"):
            link = post.find("a").get("href")
            text = post.get_text()
            results.append({"Song": text, "Link": urlsplit(link).path[1:]})
        tbl.print_rows(results)

    def get_lyrics(self, song, title=None):
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

    def print_search_results(self, query):
        soup = soupify(self.search(query))
        tbl = Table(SimpleColumn("Link", 0), SimpleColumn("Song", 0), update_width=True)
        results = []
        for post in soup.find_all("h2", class_="entry-title"):
            link = post.find("a").get("href")
            text = post.get_text()
            results.append({"Song": text, "Link": urlsplit(link).path[1:]})
        tbl.print_rows(results)

    def get_lyrics(self, song, title=None):
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


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print()
