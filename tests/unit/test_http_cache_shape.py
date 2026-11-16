"""Non-object cache metadata is a cache miss, not an AttributeError (offline, scripted)."""
import json
from pathlib import Path

import pytest

from skippercast import http
from tests import http_fixture

URL = 'https://www.example.com/feed'
HOSTS = ['www.example.com']
BODY = b'fresh'
SHAPES = [None, [], [1, 'a'], 'broken', 7, 1.5, True, False]


def _write(cache, text):
    meta_path, body_path = cache._paths(URL)
    meta_path.write_text(text)
    body_path.write_bytes(b'sentinel')
    return meta_path, body_path


@pytest.mark.parametrize('shape', SHAPES)
def test_nonobject_metadata_is_cache_miss(tmp_path, shape):
    cache = http.HTTPCache(str(tmp_path))
    text = json.dumps(shape)
    meta_path, body_path = _write(cache, text)
    assert cache.lookup(URL) is None
    assert meta_path.read_text() == text
    assert body_path.read_bytes() == b'sentinel'


@pytest.mark.parametrize('shape', SHAPES)
def test_nonobject_cache_does_not_block_request(tmp_path, shape):
    cache = http.HTTPCache(str(tmp_path))
    text = json.dumps(shape)
    meta_path, _ = _write(cache, text)
    session, script, sleeps = http_fixture.session((200, BODY, {}), cache=str(tmp_path), allowed_hosts=HOSTS)
    response = session.get(URL)
    assert (response.status, response.body, response.receipt.from_cache) == (200, BODY, False)
    assert response.receipt.attempts == 1
    assert not response.receipt.error_class
    assert len(script.requests) == 1
    assert sleeps == []
    sent = {k.lower() for k in script.requests[0].get('headers', {})} if isinstance(script.requests[0], dict) else set()
    assert not sent & {'if-none-match', 'if-modified-since'}
    assert meta_path.read_text() == text


def test_metadata_controls_preserved(tmp_path):
    cache = http.HTTPCache(str(tmp_path))
    assert cache.lookup(URL) is None  # missing
    meta_path, _ = _write(cache, '{not json')
    assert cache.lookup(URL) is None
    meta_path.write_text('{}')
    assert cache.lookup(URL) is None
    meta_path.write_text(json.dumps({'url': 'https://other.example.com/', 'etag': '"one"'}))
    assert cache.lookup(URL) is None

    fresh = tmp_path / 'valid'
    session, _, _ = http_fixture.session((200, BODY, {'ETag': '"one"'}), (304, b'', {'ETag': '"one"'}),
                                         cache=str(fresh), allowed_hosts=HOSTS)
    session.get(URL)
    hit = session.get(URL)
    assert (hit.status, hit.body, hit.receipt.from_cache) == (304, BODY, True)
