"""

"""

import json

from flask import current_app, request, Response

from ..input import parse_bool
from .._core.serialization import PermissiveJSONEncoder, yaml_dump

__all__ = ['serialize']


def serialize(data, code=200) -> Response:
    accept = request.headers.get('Accept') or ''
    if any(val in accept for val in ('application/yaml', 'application/yml')):
        resp = current_app.response_class(
            yaml_dump(data, indent_nested_lists=True, default_flow_style=False), mimetype='application/yaml'
        )
    else:
        try:
            pretty = request.args.get('pretty', default=False, type=parse_bool)
        except Exception:
            pretty = False

        if pretty:
            indent, sort_keys, seps = 2, True, (', ', ': ')
        else:
            indent, sort_keys, seps = None, False, (',', ':')

        resp = current_app.response_class(
            json.dumps(data, indent=indent, separators=seps, sort_keys=sort_keys, cls=PermissiveJSONEncoder) + '\n',
            mimetype=current_app.config['JSONIFY_MIMETYPE'],
        )

    resp.status_code = code
    return resp


class SerializableException(Exception):
    def __init__(self, payload, status_code=500):
        self.payload = payload
        self.status_code = status_code

    def as_response(self):
        payload = self.payload if not isinstance(self.payload, str) else {'message': self.payload}
        return serialize(payload, self.status_code)
