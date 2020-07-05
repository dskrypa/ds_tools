#!/usr/bin/env python

from distutils import log
from distutils.cmd import Command
from distutils.errors import DistutilsOptionError, DistutilsExecError
from itertools import chain
from pathlib import Path
from setuptools import setup, find_packages
from subprocess import Popen

project_root = Path(__file__).resolve().parent

with project_root.joinpath('readme.rst').open('r', encoding='utf-8') as f:
    long_description = f.read()

about = {}
with project_root.joinpath('ds_tools', '__version__.py').open('r', encoding='utf-8') as f:
    exec(f.read(), about)

optional_dependencies = {
    'dev': [                                            # Development env requirements
        'pre-commit',
        'psutil',
        'ipython',
    ],
    'cffi': ['cffi'],                                   # bin/cffi_test.py, bin/f3.py, examples/cffi/*
    'translate': ['googletrans'],                       # ds_tools.unicode.translate
    'J2R': ['pykakasi'],                                # ds_tools.unicode.languages
    'exif': ['exifread'],                               # bin/exif_sort.py
    'youtube': ['pytube'],                              # bin/youtube.py
    'images': ['pillow'],                               # bin/resize_images.py
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


class SetupHooksCmd(Command):
    long_description = 'Manage pre-commit hooks'
    user_options = [('install', 'i', 'Install pre-commit hooks'), ('uninstall', 'u', 'Uninstall pre-commit hooks')]
    boolean_options = ['install', 'uninstall']

    def initialize_options(self):
        self.install = None
        self.uninstall = None

    def finalize_options(self):
        options = (self.install, self.uninstall)
        if all(val is None for val in options) or all(val is not None for val in options):
            raise DistutilsOptionError('You must specify either --install xor --uninstall for pre-commit hooks')

    def run(self):
        cmd = 'install' if self.install else 'uninstall'
        self.announce('Running pre-commit {}...'.format(cmd), log.INFO)
        code = Popen(['pre-commit', cmd]).wait()
        self.announce('Result: {}'.format(code), log.DEBUG)
        if code != 0:
            raise DistutilsExecError('Error: pre-commit {} exited with a non-zero status: {}'.format(cmd, code))


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
        'Programming Language :: Python :: 3.8'
    ],
    python_requires='~=3.8',
    install_requires=requirements,
    extras_require=optional_dependencies,
    cmdclass={'hooks': SetupHooksCmd},
    scripts=['bin/{}'.format(p.name) for p in project_root.joinpath('bin').iterdir()],
)
