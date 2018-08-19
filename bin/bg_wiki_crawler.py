#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Python 3 / Requests rewrite of an old script used to pull BLU spell info from BG Wiki for FFXI to be used as an example.

:author: Doug Skrypa
"""

import argparse
import logging
import os
import sys
from bs4 import BeautifulSoup

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ds_tools.http import GenericRestClient
from ds_tools.logging import LogManager
from ds_tools.utils import Table, SimpleColumn, Printer

log = logging.getLogger("ds_tools.{}".format(__name__))


def main():
    parser = argparse.ArgumentParser(description="BG Wiki Crawler for FFXI")
    parser.add_argument("--verbose", "-v", action="count", help="Print more verbose log info (may be specified multiple times to increase verbosity)")

    mgroup0 = parser.add_mutually_exclusive_group()
    mgroup0.add_argument("--endpoint", "-e", help="BG Wiki page to retrieve")
    mgroup0.add_argument("--list_descriptions", "-d", action="store_true", help="List all BLU spell descriptions")

    parser.add_argument("--limit", "-L", type=int, default=5, help="Limit on the number of links to retrieve")
    args = parser.parse_args()
    LogManager.create_default_logger(args.verbose, log_path=None)


    crawler = WikiCrawler()
    if args.list_descriptions:
        links = crawler.get_links("index.php", params={"title":"Category:Blue_Magic"})
        # Printer("json-pretty").pprint(links)
        # return
        tbl = Table(SimpleColumn("Spell", links), SimpleColumn("Description", 100))
        for i, (spell, link) in enumerate(links.items()):
            if i == args.limit:
                break
            row = {"Spell": spell}
            try:
                row["Description"] = crawler.get_blu_spell_description(link)
            except Exception as e:
                log.error("Error retrieving {} from {}: {}".format(spell, link, e))
            tbl.print_row(row)
    elif args.endpoint:
        print(crawler.get_soup(args.endpoint))


class WikiCrawler(GenericRestClient):
    def __init__(self):
        super().__init__("www.bg-wiki.com")

    @property
    def _url_fmt(self):
        return "https://{}/{}"

    def get_soup(self, endpoint, **kwargs):
        resp = self.get(endpoint, **kwargs)
        return BeautifulSoup(resp.text, "html.parser")

    def get_links(self, endpoint, **kwargs):
        soup = self.get_soup(endpoint, **kwargs)
        anchors = {}
        for tbl in soup.find_all("table", "wikitable"):
            for tr in tbl.find_all("tr"):
                try:
                    anchor = list(tr.find_all("td"))[1].find("a")
                except IndexError:
                    pass
                else:
                    anchors[anchor.string] = anchor.get("href")
        return anchors

    def get_blu_spell_description(self, endpoint, **kwargs):
        soup = self.get_soup(endpoint, **kwargs)
        try:
            return soup.find("th", text=" Description\n").find_parent().find("td").get_text().strip()
        except AttributeError as e:
            pass
        return soup.find("b", text="Description:").find_parent().find_parent().find_all("td")[-1].get_text().strip()

    def get_blu_spell_descriptions(self, category_endpoint, **kwargs):
        links = self.get_links(category_endpoint, **kwargs)
        return {spell: self.get_blu_spell_description(link) for spell, link in links.items()}


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print()
