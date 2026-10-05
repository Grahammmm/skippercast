"""Offline doubles for skippercast.http.Session (a helper module, not a test module).

`Scripted` is a Session `connection_factory`: each request consumes the next
scripted reply, so the real Session code (retries, redirects, limits, receipts)
runs without a network. `session()` builds a Session wired to it.

`TLSServer` is a real HTTPS server on 127.0.0.1 with a throwaway CA (`make_ca`),
for tests of the actual socket, TLS and address-pinning path.
"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from pathlib import Path
import shutil
import socket
import ssl
import subprocess
import threading

from skippercast import http

PUBLIC_IP = '93.184.216.34'


def public_resolver(host, port, **_kwargs):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', (PUBLIC_IP, port))]


class FakeResponse:
    def __init__(self, status, body=b'', headers=None):
        self.status = status
        self._headers = list((headers or {}).items())
        self._body = BytesIO(body)

    def getheaders(self):
        return self._headers

    def getheader(self, name, default=None):
        return next((v for k, v in self._headers if k.lower() == name.lower()), default)

    def read(self, amount=None):
        return self._body.read(amount)


class FakeConnection:
    def __init__(self, script, host, port, addresses):
        self.script, self.host, self.port, self.addresses = script, host, port, addresses
        self.connected_address = addresses[0][1] if addresses else None

    def request(self, method, target, body=None, headers=None):
        self.script.requests.append({'method': method, 'host': self.host, 'target': target,
                                     'headers': dict(headers or {}), 'addresses': self.addresses, 'body': body})
        self.reply = self.script.replies.pop(0)

    def getresponse(self):
        if isinstance(self.reply, BaseException):
            raise self.reply
        status, body, *rest = self.reply
        return FakeResponse(status, body, rest[0] if rest else None)

    def close(self):
        pass


class Scripted:
    """Replies are (status, body[, headers]) tuples or exceptions, consumed in order."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.requests = []

    def __call__(self, host, port, addresses, *, context, timeout):
        return FakeConnection(self, host, port, addresses)


def session(*replies, **options):
    """(Session, Scripted, sleeps) with a public resolver, no proxy and recorded sleeps."""
    script = Scripted(*replies)
    sleeps = []
    options.setdefault('allowed_hosts', None)
    built = http.Session(resolver=options.pop('resolver', public_resolver), connection_factory=script,
                         proxies={}, sleep=sleeps.append, rand=lambda: 0.5,
                         context=options.pop('context', object()), **options)
    return built, script, sleeps


# ---- a real local HTTPS server (self-signed CA) --------------------------------------

HOSTNAMES = ('source.test', 'other.test')  # names on the test certificate


def make_ca(directory):
    """A throwaway CA and a leaf for HOSTNAMES, made with the openssl CLI (None if it is absent)."""
    openssl = shutil.which('openssl')
    if openssl is None:
        return None
    d = Path(directory)
    (d / 'leaf.ext').write_text(
        'basicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature\nextendedKeyUsage=serverAuth\n'
        'subjectKeyIdentifier=hash\nauthorityKeyIdentifier=keyid\n'
        'subjectAltName=' + ','.join('DNS:' + name for name in HOSTNAMES) + '\n')
    # Named curves verify under modern Python/OpenSSL; macOS LibreSSL otherwise
    # emits explicit EC parameters that the client's trust policy rejects.
    key = ['-newkey', 'ec', '-pkeyopt', 'ec_paramgen_curve:prime256v1',
           '-pkeyopt', 'ec_param_enc:named_curve', '-nodes']
    steps = [
        [openssl, 'req', '-x509', '-sha256', *key, '-keyout', 'ca.key', '-out', 'ca.pem', '-days', '2',
         '-subj', '/CN=SkipperCast test CA', '-addext', 'basicConstraints=critical,CA:TRUE',
         '-addext', 'keyUsage=critical,keyCertSign,cRLSign'],
        [openssl, 'req', '-new', '-sha256', *key, '-keyout', 'leaf.key', '-out', 'leaf.csr', '-subj', '/CN=source.test'],
        [openssl, 'x509', '-req', '-sha256', '-in', 'leaf.csr', '-CA', 'ca.pem', '-CAkey', 'ca.key', '-CAcreateserial',
         '-out', 'leaf.pem', '-days', '2', '-extfile', 'leaf.ext'],
    ]
    for step in steps:
        subprocess.run(step, cwd=d, check=True, capture_output=True, timeout=60)
    return d / 'ca.pem', d / 'leaf.pem', d / 'leaf.key'


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, *_args):
        pass

    def do_GET(self):
        self.server.fixture.serve(self)

    do_HEAD = do_POST = do_GET


class TLSServer:
    """HTTPS on 127.0.0.1 with a certificate for HOSTNAMES.

    `routes[path]` is a list of replies consumed in order (the last one repeats); a
    reply is (status, body[, headers]) or a callable(handler) returning one. Every
    request is recorded in `requests` with its SNI name, path and headers.
    """

    def __init__(self, ca, cert, key):
        self.ca = ca
        self.routes = {}
        self.requests = []
        self.sni = []
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(cert, key)
        context.sni_callback = lambda _sock, name, _ctx: self.sni.append(name)
        self.httpd = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.httpd.daemon_threads = True
        self.httpd.socket = context.wrap_socket(self.httpd.socket, server_side=True)
        self.httpd.fixture = self
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def url(self, path, host='source.test'):
        return f'https://{host}:{self.port}{path}'

    def client_context(self):
        return ssl.create_default_context(cafile=str(self.ca))

    def serve(self, handler):
        length = int(handler.headers.get('Content-Length') or 0)
        self.requests.append({'method': handler.command, 'path': handler.path,
                              'headers': {k.lower(): v for k, v in handler.headers.items()},
                              'body': handler.rfile.read(length) if length else b''})
        queue = self.routes.get(handler.path.split('?')[0])
        if not queue:
            reply = (404, b'not found')
        else:
            reply = queue.pop(0) if len(queue) > 1 else queue[0]
        if callable(reply):
            reply = reply(handler)
        status, body, *rest = reply
        headers = dict(rest[0]) if rest else {}
        handler.send_response(status)
        chunked = headers.pop('__chunked__', False)
        for name, value in headers.items():
            handler.send_header(name, value)
        if chunked:
            handler.send_header('Transfer-Encoding', 'chunked')
        elif 'Content-Length' not in headers:
            handler.send_header('Content-Length', str(len(body)))
        handler.send_header('Connection', 'close')
        handler.end_headers()
        if handler.command == 'HEAD':
            return
        if chunked:
            for start in range(0, len(body), 65536):
                piece = body[start:start + 65536]
                handler.wfile.write(b'%x\r\n' % len(piece) + piece + b'\r\n')
            handler.wfile.write(b'0\r\n\r\n')
        else:
            handler.wfile.write(body)
        handler.close_connection = True

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()
