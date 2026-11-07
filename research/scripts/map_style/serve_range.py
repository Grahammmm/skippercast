#!/usr/bin/env python3
"""Serve the repository root on localhost with HTTP Range support (PMTiles needs it).

    python research/scripts/map_style/serve_range.py [port]

Local test tool for research/scripts/map_style/bathy-deep-test.html; binds 127.0.0.1 only.
"""
import http.server
import os
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[3]


class RangeHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def send_head(self):
        match = re.fullmatch(r'bytes=(\d*)-(\d*)', self.headers.get('Range', ''))
        path = Path(self.translate_path(self.path))
        if not match or not path.is_file():
            return super().send_head()
        size = path.stat().st_size
        start, end = match.groups()
        first = size - int(end) if not start else int(start)
        last = size - 1 if not start or not end else min(int(end), size - 1)
        if first > last or first >= size:
            self.send_error(416)
            return None
        handle = path.open('rb')
        handle.seek(first)
        self.send_response(206)
        self.send_header('Content-Type', self.guess_type(str(path)))
        self.send_header('Accept-Ranges', 'bytes')
        self.send_header('Content-Range', f'bytes {first}-{last}/{size}')
        self.send_header('Content-Length', str(last - first + 1))
        self.end_headers()
        self._remaining = last - first + 1
        return handle

    def copyfile(self, source, outputfile):
        remaining = getattr(self, '_remaining', None)
        if remaining is None:
            return super().copyfile(source, outputfile)
        while remaining > 0:
            chunk = source.read(min(65536, remaining))
            if not chunk:
                break
            outputfile.write(chunk)
            remaining -= len(chunk)

    def end_headers(self):
        self.send_header('Accept-Ranges', 'bytes')
        super().end_headers()


if __name__ == '__main__':
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 18771
    server = http.server.ThreadingHTTPServer(('127.0.0.1', port), RangeHandler)
    print(f'serving {ROOT} at http://127.0.0.1:{port}/', flush=True)
    server.serve_forever()
