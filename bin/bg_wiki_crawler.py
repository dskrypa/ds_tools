#!/usr/bin/env python
"""
Python 3 / Requests rewrite of an old script used to pull BLU spell info from BG Wiki for FFXI to be used as an example.

:author: Doug Skrypa
"""

import logging

from bs4 import BeautifulSoup
from cli_command_parser import Command, ParamGroup, Option, Flag, Counter, main
from requests_client import RequestsClient

from ds_tools.output import Table, SimpleColumn
from ds_tools.output.constants import PRINTER_FORMATS

log = logging.getLogger(__name__)


class BgWikiCrawler(Command, description='BG Wiki Crawler for FFXI'):
    limit = Option('-L', default=5, type=int, help='Limit on the number of links to retrieve')

    with ParamGroup(mutually_exclusive=True):
        endpoint = Option('-e', help='BG Wiki page to retrieve')
        list_descriptions = Flag('-d', help='List all BLU spell descriptions')

    with ParamGroup(description='Common Options'):
        verbose = Counter('-v', help='Print more verbose log info (may be specified multiple times)')
        format = Option('-f', choices=PRINTER_FORMATS)

    def _init_command_(self):
        from ds_tools.logging import init_logging

        init_logging(self.verbose, log_path=None)

    def main(self):
        crawler = WikiCrawler()
        if self.list_descriptions:
            links = crawler.get_links('index.php', params={'title': 'Category:Blue_Magic'})
            # Printer('json-pretty').pprint(links)
            # return
            tbl = Table(SimpleColumn('Spell', links), SimpleColumn('Description', 100))
            for i, (spell, link) in enumerate(links.items()):
                if i == self.limit:
                    break
                row = {'Spell': spell}
                try:
                    row['Description'] = crawler.get_blu_spell_description(link)
                except Exception as e:
                    log.error(f'Error retrieving {spell} from {link}: {e}')
                tbl.print_row(row)
        elif self.endpoint:
            print(crawler.get_soup(self.endpoint))


class WikiCrawler(RequestsClient):
    def __init__(self):
        super().__init__('https://www.bg-wiki.com')

    def get_soup(self, endpoint, **kwargs):
        resp = self.get(endpoint, **kwargs)
        return BeautifulSoup(resp.text, 'html.parser')

    def get_links(self, endpoint, **kwargs):
        soup = self.get_soup(endpoint, **kwargs)
        anchors = {}
        for tbl in soup.find_all('table', 'wikitable'):
            for tr in tbl.find_all('tr'):
                try:
                    anchor = list(tr.find_all('td'))[1].find('a')
                except IndexError:
                    pass
                else:
                    anchors[anchor.string] = anchor.get('href')
        return anchors

    def get_blu_spell_description(self, endpoint, **kwargs):
        soup = self.get_soup(endpoint, **kwargs)
        try:
            return soup.find('th', text=' Description\n').find_parent().find('td').get_text().strip()
        except AttributeError:
            pass
        return soup.find('b', text='Description:').find_parent().find_parent().find_all('td')[-1].get_text().strip()

    def get_blu_spell_descriptions(self, category_endpoint, **kwargs):
        links = self.get_links(category_endpoint, **kwargs)
        return {spell: self.get_blu_spell_description(link) for spell, link in links.items()}


if __name__ == '__main__':
    main()
