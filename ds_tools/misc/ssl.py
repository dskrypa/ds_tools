from __future__ import annotations

from typing import Collection

from OpenSSL.crypto import FILETYPE_PEM, TYPE_RSA
from OpenSSL.crypto import PKey, X509Extension, X509Req, dump_privatekey, dump_certificate_request


def create_cert_request(subject_dict: dict[str, str], pw: str, sans: Collection[str] = None):
    pub_key = PKey()
    pub_key.generate_key(TYPE_RSA, 2048)

    req = X509Req()
    subject = req.get_subject()
    for key, val in subject_dict.items():
        setattr(subject, key, val)

    if sans:
        sans_str = ','.join(f'DNS:{san}' for san in sans)
        req.add_extensions([X509Extension(b'subjectAltName', False, sans_str.encode('utf-8'))])

    req.set_pubkey(pub_key)
    req.sign(pub_key, 'sha256')

    priv_key: bytes = dump_privatekey(FILETYPE_PEM, pub_key, passphrase=pw.encode('utf-8'))
    csr: bytes = dump_certificate_request(FILETYPE_PEM, req)
