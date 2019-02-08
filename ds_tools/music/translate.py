#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
"""

import logging
import os
import re
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from ds_tools.http import RestClient
from ds_tools.utils import now, FSCache, cached
from ds_tools.utils.soup import soupify, fix_html_prettify

__all__ = []
log = logging.getLogger("ds_tools.music.translate")

fix_html_prettify()


class TranslationClient(RestClient):
    def __init__(self):
        super().__init__("translate.google.com", proto="https", rate_limit=1, imitate="firefox@win10")
        cache_subdir = "{}/{}".format(self.host, now(fmt="%Y-%m-%d"))
        self._get_cache = FSCache(cache_subdir=cache_subdir, prefix="get__", ext="html")

    def get_soup(self, endpoint, **kwargs):
        return soupify(self.get(endpoint, **kwargs), "lxml")

    def start_translate(self, text, src_lang="ko", to_lang="en"):
        qs = "/#view=home&op=translate&sl={}&tl={}&text={}".format(src_lang, to_lang, text)
        return self.get(qs)

    @cached("_get_cache", lock=True, key=FSCache.html_key_nohost)
    def _translate(self, text, src_lang="ko", to_lang="en"):
        """
        This is *so close* to working...  I suspect the problem has to do with the value of the 'tk' parameter...  I
        can't figure out what the correct value to use is... It seems like it may be generated in minified and
        obfuscated javascript.

        Currently, I get a response, but no real content::\n
            <html><body><p>[[["",""],[null,null,null,""]],null,"ko",null,null,null,0,null,[["ko"],null,[0],["ko"]]]</p></body></html>

        :param str text: Text to be translated
        :param str src_lang: 2-char ISO 639-1 language code
        :param str to_lang: 2-char ISO 639-1 language code
        :return str: HTML response text
        """
        static = "hl=en&dt=at&dt=bd&dt=ex&dt=ld&dt=md&dt=qca&dt=rw&dt=rm&dt=ss&dt=t&otf=1&ssel=0&tsel=0&kc=2&tk="
        resp = self.start_translate(text, src_lang, to_lang)
        m = re.search("tkk:'(.*?)'", resp.text)
        if m:
            tk = m.group(1)
            float(tk)           # Validate that it is a valid float
            static += tk
        else:
            raise RuntimeError("Unable to parse tk value from response", resp)

        qs = "?client=webapp&sl={}&tl={}&{}q={}".format(src_lang, to_lang, static, text)
        return self.get("translate_a/single" + qs).text

    def translate(self, text, src_lang="ko", to_lang="en"):
        return soupify(self._translate(text, src_lang, to_lang), "lxml")

