"""The habitat downloader checks each range before trusting the assembled archive."""
import hashlib
from http.client import HTTPMessage

import pytest

from scripts.coast import publish_assets


PATH = '/api/habitat/tiles?region=fixture'
ARCHIVE = b'abc'
ENTRY = {'habitatRelease': 'fixture', 'bytes': len(ARCHIVE), 'sha256': hashlib.sha256(ARCHIVE).hexdigest()}


@pytest.fixture
def serve(monkeypatch):
    def install(second_headers, second_body=b'c'):
        responses = {
            'bytes=0-1': (206, {'Content-Range': 'bytes 0-1/3'}, b'ab'),
            'bytes=2-2': (206, second_headers, second_body),
        }

        def get(path, origin, headers):
            return responses[headers['Range']]

        monkeypatch.setattr(publish_assets, 'get', get)

    return install


@pytest.mark.parametrize('headers', [
    {'Content-Range': 'bytes 1-1/3'},
    {'Content-Range': 'bytes 2-3/3'},
    {},
    {'Content-Range': 'bytes 2-2/3 garbage'},
    {'Content-Range': 'bytes 2-2/4'},
    {'Content-Range': 'bytes 2-2/*'},
], ids=['wrong-start', 'wrong-end', 'missing', 'malformed', 'wrong-total', 'unknown-total'])
def test_rejects_bad_second_content_range_even_when_archive_digest_matches(serve, headers):
    # Status, body length and even the final digest cannot detect a false range declaration.
    serve(headers)
    with pytest.raises(ValueError, match=r'range 2-2.*Content-Range'):
        publish_assets.fetch(PATH, ENTRY)


def test_accepts_content_range_with_mixed_case_header_name(serve):
    # A case-sensitive header lookup would reject the second chunk of a valid archive.
    serve({'cOnTeNt-RaNgE': 'bytes 2-2/3'})
    data, _ = publish_assets.fetch(PATH, ENTRY)
    assert data == ARCHIVE


def test_rejects_conflicting_content_range_fields(serve):
    # Keeping only the first value would hide a contradictory duplicate field.
    headers = HTTPMessage()
    headers['Content-Range'] = 'bytes 2-2/3'
    headers['Content-Range'] = 'bytes 1-1/3'
    serve(headers)
    with pytest.raises(ValueError, match=r'range 2-2.*Content-Range'):
        publish_assets.fetch(PATH, ENTRY)


def test_correct_ranges_do_not_replace_the_archive_digest_check(serve):
    # A proxy can declare the right span while serving different same-length bytes.
    serve({'Content-Range': 'bytes 2-2/3'}, b'x')
    with pytest.raises(ValueError, match='bytes differ from the upstream manifest'):
        publish_assets.fetch(PATH, ENTRY)
