class ComException(Exception):
    """Base custom exception class for the ds_tools.windows package"""


class ComClassCreationException(ComException):
    pass


class IterationNotSupported(ComException):
    pass
