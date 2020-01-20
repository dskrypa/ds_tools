#!/usr/bin/env python

from pathlib import Path
from setuptools import setup, find_packages

with Path(__file__).resolve().parent.joinpath('requirements.txt').open('r') as f:
    requirements = f.read().splitlines()

setup(
    name='ds_tools',
    version='2019.04.06-1',
    author='Doug Skrypa',
    description='Misc Python 3 libraries and scripts',
    url='https://github.com/dskrypa/ds_tools',
    packages=find_packages(),
    classifiers=['Programming Language :: Python :: 3'],
    python_requires='~=3.5',
    install_requires=['wheel'] + requirements
)
