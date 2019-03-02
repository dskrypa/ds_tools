"""
ScopedSession for using SqlAlchemy in a multithreaded application

:author: Doug Skrypa
"""

import logging

from sqlalchemy.orm import mapper, sessionmaker, scoped_session

__all__ = ['ScopedSession']
log = logging.getLogger(__name__)


class ScopedSession:
    """
    Context manager for working with an SqlAlchemy scoped_session in a multithreaded environment

    :param engine: An `SqlAlchemy Engine
      <http://docs.sqlalchemy.org/en/latest/core/connections.html#sqlalchemy.engine.Engine>`_
    """
    def __init__(self, engine):
        self._scoped_session = scoped_session(sessionmaker(bind=engine))

    def __enter__(self):
        return self._scoped_session

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._scoped_session.remove()
