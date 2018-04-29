#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Very basic document storage DB using SQLAlchemy - DB portion

:author: Doug Skrypa
"""

import os
import logging

from sqlalchemy import create_engine, MetaData, Table, Column, ForeignKey, func
from sqlalchemy.types import DateTime, Integer, String, PickleType
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship, subqueryload, scoped_session
from sqlalchemy.orm.exc import NoResultFound
from sqlalchemy.exc import NoSuchTableError, OperationalError

from flask_sqlalchemy import SQLAlchemy

log = logging.getLogger("doc_store.db")
Base = declarative_base()


class Document(Base):
    __tablename__ = "docs"

    _id = Column(Integer, primary_key=True)
    id = Column(String, unique=True)
    revs = relationship("DocumentRevision", back_populates="doc", cascade="all, delete, delete-orphan")

    def __repr__(self):
        return "<{}('{}', rev={})>".format(type(self).__name__, self.id, self.rev)


def next_rev(context):
    doc_id = context.get_current_parameters()["doc_id"]
    with context.connection as conn:
        last_rev = conn.execute("SELECT max(rev) FROM revs WHERE doc_id = (?)", doc_id).first()[0]
        return last_rev + 1 if last_rev is not None else 1


class DocumentRevision(Base):
    __tablename__ = "revs"

    id = Column(Integer, primary_key=True)
    doc_id = Column(Integer, ForeignKey("docs._id"))
    content = Column(PickleType)
    rev = Column(Integer, default=next_rev)
    date = Column(DateTime, default=func.now())
    doc = relationship("Document", back_populates="revs")


class DocumentDB:
    _reserved = ("_id", "_rev", "last_modified")

    def __init__(self, db_path=None, echo=False, flask_app=None):
        self.db_path = os.path.expanduser(db_path if db_path else ":memory:")
        if self.db_path != ":memory:":
            db_dir = os.path.dirname(self.db_path)
            if not os.path.exists(db_dir):
                os.makedirs(db_dir)

        db_uri = "sqlite:///{}".format(self.db_path)
        if flask_app:
            flask_app.config["SQLALCHEMY_DATABASE_URI"] = db_uri
            self.flask_sqla = SQLAlchemy(flask_app)
            self._init_tables(self.flask_sqla.engine)
            self.db_session = self.flask_sqla.session
        else:
            self._init_tables(create_engine(db_uri, echo=echo))
            self.db_session = sessionmaker(bind=self.engine)()

    def _init_tables(self, engine):
        self.engine = engine
        self.meta = MetaData(self.engine)
        try:
            self.table = Table(Document.__tablename__, self.meta, autoload=True)
        except NoSuchTableError as e:
            Base.metadata.create_all(self.engine)
            self.table = Table(Document.__tablename__, self.meta, autoload=True)

    def doc(self, doc_id):
        try:
            return self.db_session.query(Document).options(subqueryload(Document.revs)).filter_by(id=doc_id).one()
        except (NoResultFound, OperationalError) as e:
            raise DocumentNotFoundException(doc_id) from e

    def get(self, doc_id, rev=None):
        try:
            _rev = self.doc(doc_id).revs[rev - 1 if rev is not None else -1]
        except IndexError as e:
            raise RevisionNotFoundException(doc_id, rev)
        else:
            return dict(_rev.content, _id=_rev.doc.id, _rev=_rev.rev, last_modified=_rev.date)

    def update(self, doc_id, content):
        should_add = False
        try:
            doc = self.doc(doc_id)
        except DocumentNotFoundException as e:
            doc = Document(id=doc_id)
            should_add = True

        if not isinstance(content, dict):
            content = {"data": content}
        if any(k in content for k in self._reserved):
            err_fmt = "The provided content for {} contains one or more reserved keys; the following are reserved: {}"
            raise ValueError(err_fmt.format(doc_id, ", ".join(self._reserved)))

        doc.revs.append(DocumentRevision(content=content))
        if should_add:
            self.db_session.add(doc)
        self.db_session.commit()
        return self.get(doc_id)


class DocStoreException(Exception):
    """Base Exception class for DocStore exceptions"""


class _NotFoundException(DocStoreException):
    """Exception to be raised when an item cannot be found"""
    _type = None

    def __init__(self, doc_id, rev=None):
        super().__init__()
        self.doc_id = doc_id
        self.rev = rev

    def __str__(self):
        return "{} not found: {} (rev={})".format(self._type, self.doc_id, self.rev or "latest")


class DocumentNotFoundException(_NotFoundException):
    """Exception to be raised when the requested document could not be found"""
    _type = "Document"


class RevisionNotFoundException(_NotFoundException):
    """Exception to be raised when the requested document exists, but the requested revision does not"""
    _type = "Revision"
