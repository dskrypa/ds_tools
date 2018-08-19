#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
:author: Doug Skrypa
"""

from subprocess import Popen
from tempfile import NamedTemporaryFile

from .output import Printer

__all__ = ["cdiff", "cdiff_json", "cdiff_yaml"]


def cdiff(path1, path2):
    bash_cmd = [
        "diff",
        "--old-group-format=$'%df-%dl Removed:\n\e[0;31m%<\e[0m'",
        "--new-group-format=$'%df-%dl Added:\n\e[0;32m%<\e[0m'",
        "--unchanged-group-format= -ts {} {}".format(path1, path2)
    ]
    p = Popen(["bash", "-c", " ".join(bash_cmd)])
    return p.wait()


def cdiff_objs(obj1, obj2, fmt="yaml"):
    """
    Print a comparison of the given objects when serialized with the given output format

    :param obj1: A serializable object
    :param obj2: A serializable object
    :param fmt: An output format compatible with :class:`ds_tools.utils.output.Printer`
    """
    p = Printer(fmt)
    json1 = p.pformat(obj1).encode("utf-8")
    json2 = p.pformat(obj2).encode("utf-8")
    with NamedTemporaryFile() as temp1:
        with NamedTemporaryFile() as temp2:
            temp1.write(json1)
            temp1.seek(0)
            temp2.write(json2)
            temp2.seek(0)
            return cdiff(temp1.name, temp2.name)

