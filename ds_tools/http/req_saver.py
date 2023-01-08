"""
SQLite3 DB cache for Requests response objects based on the HTTP method and URL + query string used to request it

:author: Doug Skrypa
"""

import json
import logging
import os
from urllib import parse as urllib_parse

from sqlalchemy import create_engine, MetaData, Table, Column, Integer, String, PickleType
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, scoped_session
from sqlalchemy.exc import NoSuchTableError, OperationalError, NoResultFound, MultipleResultsFound

__all__ = ['RequestSaver']
log = logging.getLogger(__name__)

METHODS = ('get', 'head', 'post', 'put', 'patch', 'delete')

Base = declarative_base()


class SavedResponse(Base):
    __tablename__ = 'responses'

    id = Column(Integer, primary_key=True)
    method = Column(String)
    url = Column(String)
    qs = Column(String)
    data_key = Column(String)
    data = Column(PickleType)
    json = Column(PickleType)
    response = Column(PickleType)

    def __repr__(self):
        if self.qs:
            return '<{}({} {}?{})>'.format(type(self).__name__, self.method, self.url, self.qs)
        return '<{}({} {})>'.format(type(self).__name__, self.method, self.url)


class NoSavedResponseException(Exception):
    """Exception to be raised when no saved response exists and responses are limited to only saved ones"""


class RequestSaver:
    """
    Replaces a :class:`requests.Session` and intercepts requests.  Saves reponses for new requests, and optionally (if
    mock is True) replays responses from previous requests for testing purposes.  Request args and the response for that
    request are stored in an sqlite3 db at db_path.
    """

    def __init__(self, session, db_path, mock=False, echo=False, sanitize=True, saved_only=False):
        self.saved_only = saved_only
        self.session = session
        self.mock = mock
        self.sanitize = sanitize
        self.db_path = os.path.expanduser(db_path if db_path else ':memory:')
        if self.db_path != ':memory:':
            db_dir = os.path.dirname(self.db_path)
            if not os.path.exists(db_dir):
                os.makedirs(db_dir)
        self.engine = create_engine('sqlite:///{}'.format(self.db_path), echo=echo)
        self.meta = MetaData(self.engine)
        try:
            self.table = Table(SavedResponse.__tablename__, self.meta, autoload=True)
        except NoSuchTableError as e:
            Base.metatdata.create_all(self.engine)
            self.table = Table(SavedResponse.__tablename__, self.meta, autoload=True)
        self.db_session = scoped_session(sessionmaker(bind=self.engine))
        for method in METHODS:
            self._add_method(method)

    def __getattr__(self, item):
        return getattr(self.session, item)

    def _add_method(self, method):
        def _request(*args, **kwargs):
            return self.request(method.upper(), *args, **kwargs)
        setattr(self, method, _request)

    @property
    def saved_responses(self):
        yield from self.db_session.query(SavedResponse)

    def request(self, method, url, *args, **kwargs):
        params = kwargs.get('params', {})
        if params:
            params = {k: v for k, v in sorted(params.items())}

        qs = urllib_parse.urlencode(params, True)

        data_key = json.dumps({k: kwargs.get(k, None) for k in ('data', 'json')}, sort_keys=True)
        req_args = {'method': method, 'url': url, 'qs': qs, 'data_key': data_key}
        try:
            saved = self.db_session.query(SavedResponse).filter_by(**req_args).one()
        except (NoResultFound, OperationalError) as e:
            # log.debug('No saved response found for {}'.format(req_args))
            saved = None
        except MultipleResultsFound as e:
            log.debug('MultipleResultsFound for {} -> {}?{} w/ data: {}'.format(method, url, qs, data_key))
            raise e

        if self.mock and saved:
            log.debug('\nReturning saved response for {} {}?{}'.format(method, url, qs))
            if isinstance(saved.response, Exception):
                raise saved.response
            return saved.response

        if self.saved_only:
            raise NoSavedResponseException('No response saved for: {}'.format(req_args))

        try:
            resp = self.session.request(method, url, *args, **kwargs)
        except Exception as e:
            resp = e
        if not saved:
            log.debug('\nSaving response for {} {}?{}'.format(method, url, qs))
            if self.sanitize:
                try:
                    orig = {}
                    for field, repl in {'request': None, 'history': [], 'cookies': {}, 'headers': {}}.items():
                        orig[field] = getattr(resp, field)
                        setattr(resp, field, repl)

                    db_resp = SavedResponse(response=resp, **req_args)
                    # log.debug('Saving: {!r}'.format(db_resp))
                    self.db_session.add(db_resp)
                    self.db_session.commit()                    # Pickling happens at commit time
                    for field, orig_content in orig.items():
                        setattr(resp, field, orig_content)
                except AttributeError:
                    pass
            else:
                db_resp = SavedResponse(response=resp, **req_args)
                # log.debug('Saving: {!r}'.format(db_resp))
                self.db_session.add(db_resp)
                self.db_session.commit()
        if isinstance(resp, Exception):
            raise resp
        return resp
