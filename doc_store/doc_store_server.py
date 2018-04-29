#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Very basic document storage DB using SQLAlchemy - server portion

:author: Doug Skrypa
"""

import argparse
import json
import logging
import socket
import traceback

from flask import Flask, request, render_template, session, redirect, g, Response
from werkzeug.http import HTTP_STATUS_CODES as codes

from doc_store_db import DocumentDB, DocStoreException

log = logging.getLogger("doc_store.server")
app = Flask("doc_store")
# app.config["APPLICATION_ROOT"] = os.environ.get("APP_PREFIX", "/")  # For future Apache support
db = DocumentDB("/var/tmp/doc_store_server.db", flask_app=app)


class ResponseException(Exception):
    def __init__(self, code, reason):
        super().__init__()
        self.code = code
        self.reason = reason
        if isinstance(reason, Exception):
            log.error(traceback.format_exc())
        log.error(self.reason)

    def __repr__(self):
        return "<{}({}, '{}')>".format(type(self).__name__, self.code, self.reason)

    def __str__(self):
        return "{}: [{}] {}".format(type(self).__name__, self.code, self.reason)

    def as_response(self):
        return Response(render_template("error.html", type=codes[self.code], reason=self.reason), self.code)


@app.errorhandler(ResponseException)
def handle_response_exception(err):
    return err.as_response()


@app.route("/")
def home():
    return render_template("error.html", type="doc_store", reason="Welcome")


@app.route("/doc/<path:doc_id>")
def get_doc(doc_id):
    rev = request.args.get("rev", None)
    if rev is not None:
        try:
            rev = int(rev)
        except ValueError as e:
            raise ResponseException(400, "Invalid revision - revisions must be positive integers >= 1")
    if isinstance(rev, int) and rev < 1:
        raise ResponseException(400, "Invalid revision - revisions must be positive integers >= 1")

    try:
        doc = db.get(doc_id, rev=rev)
    except DocStoreException as e:
        raise ResponseException(404, str(e)) from e

    doc["last_modified"] = int(doc["last_modified"].timestamp())
    return Response(json.dumps(doc, sort_keys=True, indent=4), mimetype="application/json")


@app.route("/doc/<path:doc_id>", methods=["POST", "PUT"])
def update_doc(doc_id):
    try:
        data = request.json
    except Exception as e:
        raise ResponseException(400, "Unable to parse request data as json")

    doc = db.update(doc_id, data)
    doc["last_modified"] = int(doc["last_modified"].timestamp())
    return Response(json.dumps(doc, sort_keys=True, indent=4), mimetype="application/json")


if __name__ == "__main__":
    parser = argparse.ArgumentParser("Doc Store Flask Server")
    parser.add_argument("--use_hostname", "-u", action="store_true", help="Use hostname instead of localhost/127.0.0.1")
    parser.add_argument("--port", "-p", type=int, help="Port to use")
    args = parser.parse_args()

    run_args = {"port": args.port}
    if args.use_hostname:
        run_args["host"] = socket.gethostname()

    try:
        app.run(**run_args)
    except Exception as e:
        log.debug(traceback.format_exc())
        log.error(e)
