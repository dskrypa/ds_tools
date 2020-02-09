#!/usr/bin/env python

from itertools import chain
from pathlib import Path
from setuptools import setup, find_packages

project_root = Path(__file__).resolve().parent

with project_root.joinpath('readme.rst').open('r', encoding='utf-8') as f:
    long_description = f.read()

optional_dependencies = {
    'beautifulsoup': ['beautifulsoup4'],                # ds_tools.utils.soup
    'cffi': ['cffi'],                                   # bin/cffi_test.py
    'translate': ['googletrans'],                       # ds_tools.unicode.translate
    'J2R': ['pykakasi'],                                # ds_tools.unicode.languages
    'exif': ['exifread'],                               # bin/exif_sort.py
    # 'wiki': ['mwparserfromhell', 'wikitextparser'],     # ds_tools.wiki - May not need mwparserfromhell anymore
    'wiki': ['wikitextparser'],                         # ds_tools.wiki
}
optional_dependencies['ALL'] = sorted(set(chain.from_iterable(optional_dependencies.values())))

requirements = [
    'requests_client @ git+git://github.com/dskrypa/requests_client',
    'tz_aware_dt @ git+git://github.com/dskrypa/tz_aware_dt',
    'beautifulsoup4',
    'SQLAlchemy',
    'wrapt',
    'cachetools',
    'requests',
    'tzlocal',
    'wcwidth',
    'PyYAML'
]


setup(
    name='ds_tools',
    version='2020.02.09-2',
    author='Doug Skrypa',
    author_email='dskrypa@gmail.com',
    description='Misc Python 3 libraries and scripts',
    long_description=long_description,
    url='https://github.com/dskrypa/ds_tools',
    packages=find_packages(),
    classifiers=[
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.6',    # Minimum due to use of f-strings
        'Programming Language :: Python :: 3.7',
        'Programming Language :: Python :: 3.8'
    ],
    python_requires='~=3.5',
    install_requires=requirements,
    extras_require=optional_dependencies
)
