#!/usr/bin/env python

from itertools import chain
from pathlib import Path
from setuptools import setup, find_packages

project_root = Path(__file__).resolve().parent

with project_root.joinpath('readme.rst').open('r', encoding='utf-8') as f:
    long_description = f.read()

about = {}
with project_root.joinpath('ds_tools', '__version__.py').open('r', encoding='utf-8') as f:
    exec(f.read(), about)

optional_dependencies = {
    'beautifulsoup': ['beautifulsoup4'],                # ds_tools.utils.soup
    'cffi': ['cffi'],                                   # bin/cffi_test.py
    'translate': ['googletrans'],                       # ds_tools.unicode.translate
    'J2R': ['pykakasi'],                                # ds_tools.unicode.languages
    'exif': ['exifread'],                               # bin/exif_sort.py
    'youtube': ['pytube'],                              # bin/youtube.py
}
optional_dependencies['ALL'] = sorted(set(chain.from_iterable(optional_dependencies.values())))

requirements = [
    'requests_client@ git+git://github.com/dskrypa/requests_client',
    'tz_aware_dt@ git+git://github.com/dskrypa/tz_aware_dt',
    'db_cache@ git+git://github.com/dskrypa/db_cache',
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
    name=about['__title__'],
    version=about['__version__'],
    author=about['__author__'],
    author_email=about['__author_email__'],
    description=about['__description__'],
    long_description=long_description,
    url=about['__url__'],
    project_urls={'Source': about['__url__']},
    packages=find_packages(),
    classifiers=[
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.6',    # Minimum due to use of f-strings & __set_name__
        'Programming Language :: Python :: 3.7',
        'Programming Language :: Python :: 3.8'
    ],
    python_requires='~=3.6',
    install_requires=requirements,
    extras_require=optional_dependencies
)
