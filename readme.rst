ds_tools
========

A collection of Python 3 libraries and scripts.


Installation
------------

If installing on Linux, you should run the following first::

    $ sudo apt-get install python3-dev


Regardless of OS, setuptools is required::

    $ pip install setuptools


All of the other requirements are handled in setup.py, which will be run when you install like this::

    $ pip install git+git://github.com/dskrypa/ds_tools


Clone & Install Requirements
----------------------------

To run scripts in bin, you can clone the project, then run pip install on the local project to install dependencies::

    $ git clone git://github.com/dskrypa/ds_tools
    $ cd ds_tools
    $ pip install -e .


To install optional dependencies, you can specify them like this::
    $ pip install -e .[youtube]
