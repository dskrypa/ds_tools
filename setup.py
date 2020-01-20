#!/usr/bin/env python

import re
from itertools import chain
from pathlib import Path
from setuptools import setup, find_packages

project_root = Path(__file__).resolve().parent

with project_root.joinpath('requirements.txt').open('r', encoding='utf-8') as f:
    requirements = f.read().splitlines()

with project_root.joinpath('readme.rst').open('r', encoding='utf-8') as f:
    long_description = f.read()

optional_dependencies = {
    'yaml': ['PyYAML>=5.3'],
    'beautifulsoup': ['beautifulsoup4'],
    'cffi': ['cffi'],
    'translate': ['googletrans']
}
optional_dependencies['ALL'] = sorted(set(chain.from_iterable(optional_dependencies.values())))

# Filter optional dependencies out from the contents of requirements.txt
split_pat = re.compile('^(.+?)[>=<]=')
optional_flat = set()
for dep in set(map(str.lower, chain.from_iterable(optional_dependencies.values()))):
    m = split_pat.match(dep)
    optional_flat.add(m.group(1) if m else dep)
optional_flat = tuple(optional_flat)
requirements = [req for req in requirements if not req.lower().startswith(optional_flat)]

setup(
    name='ds_tools',
    version='2020.01.20',
    author='Doug Skrypa',
    author_email='dskrypa@gmail.com',
    description='Misc Python 3 libraries and scripts',
    long_description=long_description,
    url='https://github.com/dskrypa/ds_tools',
    packages=find_packages(),
    classifiers=[
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.5',
        'Programming Language :: Python :: 3.6',
        'Programming Language :: Python :: 3.7',
        'Programming Language :: Python :: 3.8'
    ],
    python_requires='~=3.5',
    install_requires=requirements,
    extras_require=optional_dependencies
)
