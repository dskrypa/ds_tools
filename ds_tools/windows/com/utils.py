"""
Utilities for loading and working with Windows libraries using win32com.

:author: Doug Skrypa
"""

# noinspection PyUnresolvedReferences
from pythoncom import LoadTypeLib, DISPATCH_METHOD, DISPATCH_PROPERTYGET, DISPID_NEWENUM, IID_IEnumVARIANT
from win32com.client import Dispatch, DispatchBaseClass, _get_good_object_
from win32com.client.gencache import GetModuleForTypelib
from win32com.client.makepy import GenerateFromTypeLibSpec

from ..com.enums import ComClassEnum
from .exceptions import ComClassCreationException

__all__ = ['com_iter', 'create_entry', 'com_repr', 'load_module']


def load_module(dll_name: str):
    """
    :param str dll_name: A DLL file name (e.g., ``taskschd.dll``)
    :return: The loaded module
    """
    lib = LoadTypeLib(dll_name)
    iid = str(lib.GetLibAttr()[0])
    try:
        return GetModuleForTypelib(iid, 0, 1, 0)
    except ModuleNotFoundError:
        GenerateFromTypeLibSpec(dll_name, None, verboseLevel=0, bForDemand=0, bBuildHidden=1)
        return GetModuleForTypelib(iid, 0, 1, 0)


def create_entry(collection: DispatchBaseClass, _type: int, lcid=0):
    """
    Create an entry in a collection with the specified type.  Returns the correct entry type, assumed to be a subclass
    of the generic/base type, instead of the generic/base type that the gen_py generated code returns.

    :param collection: A win32com-generated Collection class (e.g., ``ITriggerCollection`` or ``IActionCollection``)
    :param int _type: The type enum representing the type of entry to create (e.g.,
      ``taskschd.constants.TASK_ACTION_EXEC`` or ``taskschd.constants.TASK_TRIGGER_TIME``)
    :param lcid: The LCID for the library
    :return: The created entry
    """
    memid = _get_create_memid(collection)
    result = collection._oleobj_.InvokeTypes(memid, lcid, 1, (9, 0), ((3, 1),), _type)
    if result is None:
        if (enum := ComClassEnum._get_entry_enum(collection.__class__.CLSID)) and (cls := enum.for_num(_type, None)):
            # noinspection PyUnboundLocalVariable
            raise ComClassCreationException(f'Unable to create {cls.cls.__name__} in {collection=}')
        raise ComClassCreationException(f'Unable to create entry in {collection=}')
    return Dispatch(result, 'Create')


def com_iter(obj: DispatchBaseClass, lcid=0):
    """
    Iterate over the items that the given COM object contains.  Yields the proper classes rather than the base classes.
    """
    invkind = DISPATCH_METHOD | DISPATCH_PROPERTYGET
    enum = obj._oleobj_.InvokeTypes(DISPID_NEWENUM, lcid, invkind, (13, 10), ())
    for value in enum.QueryInterface(IID_IEnumVARIANT):
        yield _get_good_object_(value)  # When no clsid is provided, it returns the correct subclass


def com_repr(obj):
    if isinstance(obj, DispatchBaseClass):
        attr_names = obj._prop_map_get_
        return '<{}[{}]>'.format(
            obj.__class__.__name__, ', '.join(f'{k}={com_repr(getattr(obj, k))}' for k in attr_names)
        )
    else:
        return repr(obj)


def _get_func_descs(type_info, type_attr):
    descs = {}
    for i in range(type_attr.cFuncs):
        desc = type_info.GetFuncDesc(i)
        name = type_info.GetNames(desc.memid)[0]
        descs[name] = desc
    return descs


def _get_create_memid(collection: DispatchBaseClass):
    type_info = collection._oleobj_.GetTypeInfo()
    type_attr = type_info.GetTypeAttr()
    desc = _get_func_descs(type_info, type_attr)['Create']
    return desc.memid
