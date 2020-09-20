"""
:author: Doug Skrypa
"""

import re
from itertools import chain

from ds_tools.utils.text_processing import regexcape

__all__ = ['synonym_pattern']

SYNONYM_SETS = [{'and', '&', '+'}, {'version', 'ver.'}]


def synonym_pattern(text, synonym_sets=None, chain_sets=True):
    """
    :param str text: Text from which a regex pattern should be generated
    :param synonym_sets: Iterable that yields sets of synonym strings, or None to use :data:`SYNONYM_SETS`
    :param bool chain_sets: Chain the given synonym_sets with :data:`SYNONYM_SETS` (if False: only consider the provided
      synonym_sets)
    :return: Compiled regex pattern for the given text that will match the provided synonyms
    """
    parts = [regexcape(part) for part in re.split(r'(\W)', re.sub(r'\s+', ' ', text.lower())) if part]
    synonym_sets = chain(SYNONYM_SETS, synonym_sets) if chain_sets and synonym_sets else synonym_sets or SYNONYM_SETS

    for synonym_set in synonym_sets:
        for i, part in enumerate(list(parts)):
            if part in synonym_set:
                parts[i] = '(?:{})'.format('|'.join(regexcape(s) for s in sorted(synonym_set)))

    pattern = ''.join(r'\s+' if part == ' ' else part for part in parts)
    # log.debug('Synonym pattern: {!r} => {!r}'.format(text, pattern))
    return re.compile(pattern, re.IGNORECASE)
