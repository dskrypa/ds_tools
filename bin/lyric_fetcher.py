#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Fetch Korean lyrics and fix the html to make them easier to print

:author: Doug Skrypa
"""

import argparse
import collections
import logging
import os
import re
import sys
from abc import ABCMeta, abstractmethod
from bs4 import BeautifulSoup, DEFAULT_OUTPUT_ENCODING
from bs4.element import AttributeValueWithCharsetSubstitution, EntitySubstitution, NavigableString, Tag, PageElement
from collections import defaultdict
from urllib.parse import urlsplit

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ds_tools.http import GenericRestClient
from ds_tools.logging import LogManager
from ds_tools.utils import Table, SimpleColumn, validate_or_make_dir

log = logging.getLogger("ds_tools.{}".format(__file__))

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
    parser.add_argument("--site", "-S", choices=SITES, default="colorcodedlyrics", help="Site from which lyrics should be retrieved (default: %(default)s)")
    args = parser.parse_args()
    LogManager.create_default_logger(args.verbose, log_path=None)

    if args.site == "colorcodedlyrics":
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


class LyricFetcher(GenericRestClient, metaclass=ABCMeta):
    def __init__(self, *args, **kwargs):
        validate_or_make_dir(CACHE_DIR)
        super().__init__(*args, **kwargs)

    @abstractmethod
    def search(self, query):
        return None

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
        cache_file = "{}/get_{}_{}.html".format(CACHE_DIR, self.host, endpoint.replace("/", "_"))
        if os.path.exists(cache_file):
            with open(cache_file, "r", encoding="utf-8") as f:
                return f.read()

        resp = super().get(endpoint, **kwargs)
        with open(cache_file, "w", encoding="utf-8") as f:
            f.write(resp.text)

        return resp.text


class KlyricsLyricFetcher(LyricFetcher):
    def __init__(self):
        super().__init__("klyrics.net", proto="https")

    def search(self, query):
        return None

    def print_search_results(self, query):
        return None

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

            ele = h2.next_sibling
            while ele.name in (None, "p"):
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

    def search(self, query):
        cache_file = "{}/search_{}.html".format(CACHE_DIR, query.replace(" ", "_"))
        if os.path.exists(cache_file):
            with open(cache_file, "r", encoding="utf-8") as f:
                return f.read()

        resp = super().get("/", params={"s": query})
        with open(cache_file, "w", encoding="utf-8") as f:
            f.write(resp.text)

        return resp.text

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


def soupify(resp, mode="html.parser"):
    if not isinstance(resp, str):
        resp = resp.text
    return BeautifulSoup(resp, mode)


def decode(self, indent_level=None, eventual_encoding=DEFAULT_OUTPUT_ENCODING, formatter="minimal"):
    """Returns a Unicode representation of this tag and its contents.

    :param eventual_encoding: The tag is destined to be encoded into this encoding. This method is _not_ responsible
      for performing that encoding. This information is passed in so that it can be substituted in if the document
      contains a <META> tag that mentions the document's encoding.
    """
    # First off, turn a string formatter into a function. This will stop the lookup from happening over and over again.
    if not isinstance(formatter, collections.Callable):
        formatter = self._formatter_for_name(formatter)

    attrs = []
    if self.attrs:
        for key, val in sorted(self.attrs.items()):
            if val is None:
                decoded = key
            else:
                if isinstance(val, list) or isinstance(val, tuple):
                    val = " ".join(val)
                elif not isinstance(val, str):
                    val = str(val)
                elif isinstance(val, AttributeValueWithCharsetSubstitution) and eventual_encoding is not None:
                    val = val.encode(eventual_encoding)

                text = self.format_string(val, formatter)
                decoded = str(key) + "=" + EntitySubstitution.quoted_attribute_value(text)
            attrs.append(decoded)

    close, closeTag, prefix, space, indent_space = "", "", "", "", ""

    if self.prefix:
        prefix = self.prefix + ":"

    if self.is_empty_element:
        close = "/"
    else:
        closeTag = "</%s%s>" % (prefix, self.name)

    pretty_print = self._should_pretty_print(indent_level)
    has_nested = any(isinstance(c, Tag) for c in self)

    if indent_level is not None:
        indent_space = "    " * (indent_level - 1)

    if pretty_print:
        space = indent_space
        indent_contents = None if not has_nested else indent_level + 1  # Prevent extra newline on deepest nested level
    else:
        indent_contents = None

    contents = self.decode_contents(indent_contents, eventual_encoding, formatter)

    if self.hidden:
        # This is the 'document root' object.
        s = contents
    else:
        s = []
        if indent_level is not None:
            # Even if this particular tag is not pretty-printed, we should indent up to the start of the tag.
            s.append(indent_space)

        attribute_string = ""
        if attrs:
            attribute_string = " " + " ".join(attrs)
        s.append("<%s%s%s%s>" % (prefix, self.name, attribute_string, close))
        if close:
            s.append("\n")

        if has_nested and pretty_print:
            s.append("\n")

        s.append(contents)

        if has_nested and pretty_print:
            if contents and contents[-1] != "\n":
                s.append("\n")
            if closeTag:
                s.append(space)
        s.append(closeTag)

        if indent_level is not None and closeTag and self.next_sibling:
            # Even if this particular tag is not pretty-printed, we're now done with the tag, and we should add a
            # newline if appropriate.
            s.append("\n")
        s = "".join(s)
    return s


def decode_contents(self, indent_level=None, eventual_encoding=DEFAULT_OUTPUT_ENCODING, formatter="minimal"):
    """Renders the contents of this tag as a Unicode string.

    :param indent_level: Each line of the rendering will be indented this many spaces.
    :param eventual_encoding: The tag is destined to be encoded into this encoding. This method is _not_ responsible
      for performing that encoding. This information is passed in so that it can be substituted in if the document
      contains a <META> tag that mentions the document's encoding.
    :param formatter: The output formatter responsible for converting entities to Unicode characters.
    """
    # First off, turn a string formatter into a function. This will stop the lookup from happening over and over again.
    if not isinstance(formatter, collections.Callable):
        formatter = self._formatter_for_name(formatter)

    pretty_print = (indent_level is not None)
    s = []
    for c in self:
        text = None
        if isinstance(c, NavigableString):
            text = c.output_ready(formatter)
        elif isinstance(c, Tag):
            s.append(c.decode(indent_level, eventual_encoding, formatter))
        if text and indent_level and not self.name == "pre":
            text = text.strip()
        if text:
            if pretty_print and not self.name == "pre":
                s.append("    " * (indent_level - 1))
            s.append(text)
            if pretty_print and not self.name == "pre":
                s.append("\n")
    return "".join(s)


PageElement.decode = decode
PageElement.decode_contents = decode_contents
Tag.decode = decode
Tag.decode_contents = decode_contents


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print()
