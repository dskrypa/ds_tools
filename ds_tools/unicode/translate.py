"""
Library for translating text from one language to another

:author: Doug Skrypa
"""

import logging

from googletrans import Translator

from ..caching import cached, DBCache
from ..core import rate_limited
from ..http.sessions import IMITATE_HEADERS

__all__ = ['GoogleTranslator']
log = logging.getLogger(__name__)


def translate_key(text, dest, src):
    return text, dest, src


class GoogleTranslator(Translator):
    """
    Wrapper around py-googletrans' Translator to imitate additional browser headers, to cache translations, and to
    rate-limit translation requests.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.session.headers.update(IMITATE_HEADERS['firefox@win10'])
        self._resp_cache = DBCache('translations', cache_subdir='translate')
        self._translate = cached(self._resp_cache, lock=True, key=translate_key)(self._translate)
        self._translate = rate_limited(1)(self._translate)

    def ko2en(self, text):
        return self.translate(text, 'en', 'ko')
