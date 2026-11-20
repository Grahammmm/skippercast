"""F32-04: the local PMTiles handler serves ranges without a network socket."""
from email.parser import BytesParser
from io import BytesIO
from unittest.mock import Mock

import pytest

from research.scripts.map_style import serve_range


@pytest.mark.parametrize(('payload', 'range_value', 'status', 'content_range', 'body'), [
    (b'abcdef', 'bytes=-9', 206, 'bytes 0-5/6', b'abcdef'),
    (b'abcdef', 'bytes=-2', 206, 'bytes 4-5/6', b'ef'),
    (b'abcdef', 'bytes=1-3', 206, 'bytes 1-3/6', b'bcd'),
    (b'abcdef', 'bytes=6-', 416, 'bytes */6', b''),
    (b'abcdef', 'bytes=3-1', 416, 'bytes */6', b''),
    (b'abcdef', 'bytes=-0', 416, 'bytes */6', b''),
    (b'', 'bytes=-1', 416, 'bytes */0', b''),
    (b'abcdef', 'bytes=-', 200, None, b'abcdef'),
])
def test_preview_range_response(tmp_path, monkeypatch, payload, range_value, status, content_range, body):
    """An oversized suffix used to seek before byte zero instead of returning the archive."""
    (tmp_path / 'fixture.pmtiles').write_bytes(payload)
    monkeypatch.setattr(serve_range, 'ROOT', tmp_path)
    request = Mock()
    request.makefile.return_value = BytesIO(
        f'GET /fixture.pmtiles HTTP/1.0\r\nRange: {range_value}\r\n\r\n'.encode('ascii')
    )
    serve_range.RangeHandler(request, ('127.0.0.1', 0), None)
    response = b''.join(call.args[0] for call in request.sendall.call_args_list)
    head, actual_body = response.split(b'\r\n\r\n', 1)
    status_line, raw_headers = head.split(b'\r\n', 1)
    headers = BytesParser().parsebytes(raw_headers)
    assert int(status_line.split()[1]) == status
    assert headers['Content-Range'] == content_range
    assert headers['Content-Length'] == str(len(body))
    assert actual_body == body
