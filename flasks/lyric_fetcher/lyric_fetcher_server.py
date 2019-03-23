#!/usr/bin/env python3
"""
Flask server for cleaning up Korean to English translations of song lyrics to make them easier to print

:author: Doug Skrypa
"""

import argparse
import logging
import socket
import sys
import traceback
from pathlib import Path
from urllib.parse import urlencode

from flask import Flask, request, render_template, redirect, Response, url_for
from flask_socketio import SocketIO
from werkzeug.http import HTTP_STATUS_CODES as codes

flask_dir = Path(__file__).resolve().parent
sys.path.append(flask_dir.parents[1].as_posix())
from ds_tools.logging import LogManager
from ds_tools.lyric_fetcher import SITE_CLASS_MAPPING, normalize_lyrics, fix_links

log = logging.getLogger('lyric_fetcher.server')
app = Flask(
    __name__,
    static_folder=flask_dir.joinpath('static').as_posix(),
    template_folder=flask_dir.joinpath('templates').as_posix()
)
app.config.update(PROPAGATE_EXCEPTIONS=True, JSONIFY_PRETTYPRINT_REGULAR=True)

DEFAULT_SITE = 'colorcodedlyrics'
SITES = list(SITE_CLASS_MAPPING.keys())
fetchers = {site: fetcher_cls() for site, fetcher_cls in SITE_CLASS_MAPPING.items()}


@app.route('/')
def home():
    url = url_for('.search')
    log.info('Redirecting from / to {}'.format(url))
    return redirect(url)


@app.route('/search/', methods=['GET', 'POST'])
def search():
    req_is_post = request.method == 'POST'
    params = {}
    for param in ('q', 'subq', 'site', 'index'):
        value = request.form.get(param)
        if value is None:
            value = request.args.get(param)
        if value is not None:
            if isinstance(value, str):
                value = value.strip()
                if value:
                    params[param] = value
            else:
                params[param] = value

    if req_is_post:
        redirect_to = url_for('.search')
        if params:
            redirect_to += '?' + urlencode(params, True)
        return redirect(redirect_to)

    query = params.get('q')                     # query
    sub_query = params.get('subq')              # sub query
    site = params.get('site') or DEFAULT_SITE   # site from which results should be retrieved
    index = params.get('index')                 # bool: show index results instead of search results

    form_values = {'query': query, 'sub_query': sub_query, 'site': site, 'index': index}
    render_vars = {
        'title': 'Lyric Fetcher - Search', 'form_values': form_values, 'sites': SITES
    }

    if not query:
        # noinspection PyUnresolvedReferences
        return render_template('search.html', error='You must provide a valid query.', **render_vars)
    elif site not in fetchers:
        # noinspection PyUnresolvedReferences
        return render_template('search.html', error='Invalid site.', **render_vars)

    fetcher = fetchers[site]
    if index:
        try:
            results = fetcher.get_index_results(query)
        except TypeError as e:
            raise ResponseException(501, str(e))
    else:
        results = fetcher.get_search_results(query, sub_query)

    fix_links(results)
    if not results:
        # noinspection PyUnresolvedReferences
        return render_template('search.html', error='No results.', **render_vars)

    # noinspection PyUnresolvedReferences
    return render_template('search.html', results=results, **render_vars)


@app.route('/song/<path:song>', methods=['GET'])
def song(song):
    site = request.args.get('site') or DEFAULT_SITE
    if site not in fetchers:
        raise ResponseException(400, 'Invalid site.')

    alt_title = request.args.get('title')
    ignore_len = request.args.get('ignore_len', type=bool)
    fetcher = fetchers[site]

    lyrics = fetcher.get_lyrics(song, alt_title)
    discovered_title = lyrics.pop('title', None)
    stanzas = normalize_lyrics(lyrics, ignore_len=ignore_len)
    stanzas['Translation'] = stanzas.pop('English')

    max_stanzas = max(len(lang_stanzas) for lang_stanzas in stanzas.values())
    for lang, lang_stanzas in stanzas.items():
        add_stanzas = max_stanzas - len(lang_stanzas)
        if add_stanzas:
            for i in range(add_stanzas):
                lang_stanzas.append([])

    render_vars = {
        'title': alt_title or discovered_title or song, 'lyrics': stanzas, 'lang_order': ['Korean', 'Translation'],
        'stanza_count': max_stanzas
    }
    # noinspection PyUnresolvedReferences
    return render_template('song.html', **render_vars)


class ResponseException(Exception):
    def __init__(self, code, reason):
        super().__init__()
        self.code = code
        self.reason = reason
        if isinstance(reason, Exception):
            log.error(traceback.format_exc())
        log.error(self.reason)

    def __repr__(self):
        return '<{}({}, {!r})>'.format(type(self).__name__, self.code, self.reason)

    def __str__(self):
        return '{}: [{}] {}'.format(type(self).__name__, self.code, self.reason)

    def as_response(self):
        # noinspection PyUnresolvedReferences
        rendered = render_template('layout.html', error_code=codes[self.code], error=self.reason)
        return Response(rendered, self.code)


@app.errorhandler(ResponseException)
def handle_response_exception(err):
    return err.as_response()


if __name__ == '__main__':
    parser = argparse.ArgumentParser('Lyric Fetcher Flask Server')
    parser.add_argument('--use_hostname', '-u', action='store_true', help='Use hostname instead of localhost/127.0.0.1')
    parser.add_argument('--port', '-p', type=int, help='Port to use')
    parser.add_argument('--verbose', '-v', action='count', help='Print more verbose log info (may be specified multiple times to increase verbosity)')
    args = parser.parse_args()
    lm = LogManager.create_default_logger(args.verbose, log_path=None)

    flask_logger = logging.getLogger('flask.app')
    for handler in lm.logger.handlers:
        if handler.name == 'stderr':
            flask_logger.addHandler(handler)

    run_args = {'port': args.port}
    if args.use_hostname:
        run_args['host'] = socket.gethostname()

    socketio = SocketIO(app, async_mode='eventlet')
    try:
        socketio.run(app, **run_args)
        # app.run(**run_args)
    except Exception as e:
        log.debug(traceback.format_exc())
        log.error(e)
