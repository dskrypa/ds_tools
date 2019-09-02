#!/usr/bin/env python3
"""
Flask server for updating song metadata

:author: Doug Skrypa
"""

import argparse
import logging
import signal
import socket
import sys
import traceback
from pathlib import Path
from urllib.parse import urlencode

import eventlet
from flask import Flask, request, render_template, redirect, Response, url_for
from flask_socketio import SocketIO
from werkzeug.http import HTTP_STATUS_CODES as codes

flask_dir = Path(__file__).resolve().parent
sys.path.append(flask_dir.parents[1].as_posix())
from ds_tools.logging import LogManager
from ds_tools.music import (
    iter_music_files, load_tags, iter_music_albums, iter_categorized_music_files, tag_repr, apply_mutagen_patches,
    TagException, iter_album_dirs, RM_TAGS_ID3, RM_TAGS_MP4, NoPrimaryArtistError, WikiSoundtrack
)

apply_mutagen_patches()

log = logging.getLogger('ds_tools.music_manager.server')
app = Flask(
    __name__,
    static_folder=flask_dir.joinpath('static').as_posix(),
    template_folder=flask_dir.joinpath('templates').as_posix()
)
app.config.update(PROPAGATE_EXCEPTIONS=True, JSONIFY_PRETTYPRINT_REGULAR=True)


@app.route('/')
def home():
    url = url_for('.process_songs')
    log.info('Redirecting from / to {}'.format(url))
    return redirect(url)


@app.route('/update_songs/')
def update_songs():
    raise ResponseException(501, 'Not available yet.')


@app.route('/process_songs/', methods=['GET', 'POST'])
def process_songs():
    req_is_post = request.method == 'POST'
    params = {}
    for param in ('src_path', 'dest_path', 'include_osts'):
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
        redirect_to = url_for('.process_songs')
        if params:
            redirect_to += '?' + urlencode(params, True)
        return redirect(redirect_to)

    if not params.get('src_path'):
        return render_template('layout.html', form_values={})

    src_path = Path(params.get('src_path'))
    dest_path = Path(params['dest_path']) if params.get('dest_path') else None
    include_osts = params.get('include_osts')

    form_values = {'src_path': src_path, 'dest_path': dest_path}
    render_vars = {'form_values': form_values}

    if not src_path.exists():
        raise ResponseException(400, 'The source path {} does not exist!'.format(src_path.as_posix()))
    if dest_path and dest_path.is_file():
        raise ResponseException(400, 'The destination path {} is invalid!'.format(dest_path.as_posix()))

    render_vars['results'] = match_wiki(src_path, include_osts)
    return render_template('layout.html', **render_vars)


def set_ost_filter(path, include_osts=False):
    if include_osts:
        WikiSoundtrack._search_filters = None
    else:
        ost_filter = set()
        for f in iter_music_files(path):
            ost_filter.add(f.album_name_cleaned)
            ost_filter.add(f.dir_name_cleaned)

        WikiSoundtrack._search_filters = ost_filter

    log.debug('OST Search Filter: {}'.format(WikiSoundtrack._search_filters))


def match_wiki(path, include_osts):
    set_ost_filter(path, include_osts)
    rows = []
    for music_file in iter_music_files(path):
        row = {'path': music_file.path.as_posix(), 'fields': [], 'scores': {}, 'error': None}
        try:
            fields = row['fields']
            try:
                fields.append({'name': 'artist', 'original': music_file.tag_artist, 'new': music_file.wiki_artist.qualname if music_file.wiki_artist else ''})
            except NoPrimaryArtistError as e:
                fields.append({'name': 'artist', 'original': music_file.tag_artist, 'new': music_file.tag_artist})

            fields.append({'name': 'album', 'original': music_file.album_name_cleaned, 'new': music_file.wiki_album.title() if music_file.wiki_album else ''})
            fields.append({'name': 'album_type', 'original': music_file.album_type_dir, 'new': music_file.wiki_album.album_type if music_file.wiki_album else ''})
            row['scores']['album'] = music_file.wiki_scores.get('album', -1)

            fields.append({'name': 'title', 'original': music_file.tag_title, 'new': music_file.wiki_song.long_name if music_file.wiki_song else ''})
            row['scores']['track'] = music_file.wiki_scores.get('song', -1)

            fields.append({'name': 'track', 'original': int(music_file.track_num) if music_file.track_num else '', 'new': int(music_file.wiki_song.num) if music_file.wiki_song else ''})
            fields.append({'name': 'disk', 'original': int(music_file.disk_num) if music_file.disk_num else '', 'new': int(music_file.wiki_song.disk) if music_file.wiki_song else ''})
        except Exception as e:
            log.error('Error processing {}: {}'.format(music_file, e), extra={'color': (15, 9)})
            log.log(19, traceback.format_exc())
            row['error'] = traceback.format_exc()

        rows.append(row)
    return rows


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


def exit(*args):
    log.warning('Exiting')
    sys.exit(0)


if __name__ == '__main__':
    parser = argparse.ArgumentParser('Music Manager Flask Server')
    parser.add_argument('--use_hostname', '-u', action='store_true', help='Use hostname instead of localhost/127.0.0.1')
    parser.add_argument('--port', '-p', type=int, help='Port to use', required=True)
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

    signal.signal(signal.SIGTERM, exit)
    signal.signal(signal.SIGINT, exit)

    socketio = SocketIO(app, async_mode='eventlet')
    try:
        socketio.run(app, **run_args)
        # app.run(**run_args)
    except Exception as e:
        log.debug(traceback.format_exc())
        log.error(e)
