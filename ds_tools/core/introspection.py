"""
Introspection utilities that build upon the built-in introspection module.

:author: Doug Skrypa
"""

import re
from collections import OrderedDict
from contextlib import suppress
from inspect import Signature, Parameter, _empty

__all__ = ['arg_vals_with_defaults', 'split_arg_vals_with_defaults', 'insert_kwonly_arg']


def arg_vals_with_defaults(sig, *args, **kwargs):
    """
    Assigns *args and **kwargs parameters to named variables based on the given signature.  Applies default values for
    parameters that were not given a value.

    This is based on :func:`inspect.BoundArguments.apply_defaults`, which does not exist in Python < 3.5, and does not
    apply defaults when no arguments were provided (i.e., all defaults are being used).

    For variable-positional arguments (*args), the default is an empty tuple.
    For variable-keyword arguments (**kwargs), the default is an empty dict.

    :param Signature sig: The signature of the function the given args are for
    :param args: Positional arguments explicitly provided for the function
    :param kwargs: Keyword args explicitly provided for the function
    :return OrderedDict: Mapping of arg:value, including defaults from sig
    """
    vals = sig.bind(*args, **kwargs).arguments
    new_args = OrderedDict()
    for name, param in sig.parameters.items():
        try:
            new_args[name] = vals[name]
        except KeyError:
            if param.default is not _empty:
                new_args[name] = param.default
            elif param.kind == Parameter.VAR_POSITIONAL:
                new_args[name] = ()
            elif param.kind == Parameter.VAR_KEYWORD:
                new_args[name] = {}
    return new_args


def split_arg_vals_with_defaults(sig, *args, **kwargs):
    """
    Inserts default values where applicable in the given *args and **kwargs based on the given Signature.

    This is based on :func:`inspect.BoundArguments.apply_defaults`, which does not exist in Python < 3.5, and does not
    apply defaults when no arguments were provided (i.e., all defaults are being used).

    :param Signature sig: The signature of the function the given arguments are for
    :param args: Positional arguments explicitly provided for the function with the given signature
    :param kwargs: Keyword args explicitly provided for the function with the given signature
    :return tuple: (List of args that can be provided as positional, Mapping of arg:value)
    """
    vals = sig.bind(*args, **kwargs).arguments
    args_out = []
    kwargs_out = OrderedDict()
    for name, param in sig.parameters.items():
        if param.kind == Parameter.VAR_KEYWORD:
            with suppress(KeyError):
                kwargs_out.update(vals[name])
        elif param.kind == Parameter.VAR_POSITIONAL:
            with suppress(KeyError):
                args_out.extend(vals[name])
        elif param.kind in (Parameter.POSITIONAL_ONLY, Parameter.POSITIONAL_OR_KEYWORD):
            try:
                args_out.append(vals[name])
            except KeyError:
                if param.default is not _empty:
                    args_out.append(param.default)
        else:
            try:
                kwargs_out[name] = vals[name]
            except KeyError:
                if param.default is not _empty:
                    kwargs_out[name] = param.default
    return args_out, kwargs_out


def insert_kwonly_arg(func, param, description, param_type='', sig=None):
    """
    Updates the given function in-place to add the given parameter to its signature and docstring.

    :param func: A function
    :param Parameter param: A :class:`inspect.Parameter`
    :param str description: The parameter description to include in the docstring
    :param str param_type: The type to include in the docstring
    :param Signature sig: The :class:`inspect.Signature` of the function if it is already known
    :return: The updated function
    :raises: ValueError if param.kind is not ``Parameter.KEYWORD_ONLY``
    """
    if param.kind != Parameter.KEYWORD_ONLY:
        raise ValueError('Only KEYWORD_ONLY parameters are supported; found: {}'.format(param))
    sig = sig or Signature.from_callable(func)
    params = list(sig.parameters.values())
    sig_pos = len(params)
    prev = None
    for i, p in enumerate(params):
        if p.kind in (Parameter.KEYWORD_ONLY, Parameter.VAR_KEYWORD):
            sig_pos = i
            prev = params[i]
            break
    if not prev and sig_pos > 0:
        prev = params[sig_pos - 1]

    if prev and func.__doc__ and any(txt in func.__doc__ for txt in (':param', ':return')):
        prev_rx = re.compile(':param (?<!:){}:.*'.format(prev.name))
        indent_rx = re.compile('^(\s+):.*')
        doc = func.__doc__.splitlines()
        doc_pos = len(doc)
        found = False
        indent = ''
        for i, line in enumerate(doc):
            sline = line.strip()
            if sline.startswith(':'):
                if not indent:
                    m = indent_rx.match(line)
                    if m:
                        indent = m.group(1)

                if not found:
                    if prev_rx.match(sline) or sline.startswith(':return'):
                        found = True
                else:
                    if sline.startswith(':param'):
                        doc_pos = i
                        break

                if sline.startswith(':return'):
                    doc_pos = i
                    break

        param_doc = '{}:param {}{}{}: {}'.format(indent, param_type, ' ' if param_type else '', param.name, description)
        if param.default is not _empty:
            param_doc += ' (default: {})'.format(param.default)
        doc.insert(doc_pos, param_doc)
        func.__doc__ = '\n'.join(doc)
    params.insert(sig_pos, param)
    func.__signature__ = Signature(params)
    return func
