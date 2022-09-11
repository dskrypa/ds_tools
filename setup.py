#!/usr/bin/env python

from itertools import chain
from pathlib import Path
from setuptools import setup, find_packages

project_root = Path(__file__).resolve().parent
long_description = project_root.joinpath('readme.rst').read_text('utf-8')

about = {}
with project_root.joinpath('ds_tools', '__version__.py').open('r', encoding='utf-8') as f:
    exec(f.read(), about)

# scripts = ['bin/{}'.format(p.name) for p in project_root.joinpath('bin').iterdir()]

optional_dependencies = {
    'archives': ['py7zr', 'rarfile', 'cryptography'],   # ds_tools.fs.archives
    'cffi': ['cffi'],                                   # bin/cffi_test.py, bin/f3.py, examples/cffi/*
    'click': ['click', 'click_option_group'],           # ds_tools.argparsing.click_parsing
    'completion': ['argcomplete'],                      # bash autocompletion
    'dev': [                                            # Development env requirements
        'coverage',
        'ipython',
        'pre-commit',                                   # run `pre-commit install` to install hooks
    ],
    'docs': ['sphinx'],
    'exif': ['exifread'],                               # bin/exif_sort.py
    'flask': ['flask', 'jinja2', 'werkzeug'],           # flasks package
    'gunicorn': ['gevent', 'gunicorn'],                 # flasks package with gunicorn
    'images': [                                         # bin/resize_images.py, ds_tools.images.*
        'imageio',
        'numpy',
        'pillow',
        'scikit-image; python_version < "3.10"',  # package: skimage; required scipy, which breaks in python 3.10
        # 'scipy',
    ],
    'J2R': ['pykakasi'],                                # ds_tools.unicode.languages
    'pdf': ['pypdf2'],                                  # bin/pdf_merge.py
    'socketio': ['flask_socketio', 'gevent'],           # flasks package with socketio
    'translate': ['googletrans'],                       # ds_tools.unicode.translate
    'windows': ['pywin32'],                             # bin/windows_tasks.py
    'youtube': ['pytube3'],                             # bin/youtube.py
}
optional_dependencies['ALL'] = sorted(set(chain.from_iterable(optional_dependencies.values())))

requirements = [
    'cli_command_parser>=2022.9.11',
    'db_cache@ git+https://github.com/dskrypa/db_cache',
    'requests_client@ git+https://github.com/dskrypa/requests_client',
    'tz_aware_dt@ git+https://github.com/dskrypa/tz_aware_dt',
    'beautifulsoup4',
    'bitarray',
    'cachetools',
    'psutil',
    'PyYAML',
    'requests',
    'SQLAlchemy',
    'tzlocal',
    'wrapt',
    'wcwidth',
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
        'Programming Language :: Python :: 3.8',
        'Programming Language :: Python :: 3.9',
        'Programming Language :: Python :: 3.10',
    ],
    python_requires='>=3.8',
    install_requires=requirements,
    extras_require=optional_dependencies,
    # scripts=scripts,
)
