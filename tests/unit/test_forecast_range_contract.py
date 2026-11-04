"""Forecast ranged GETs: only an exact 206 slice reaches the GRIB decoder; ordinary requests and the ECMWF mirror stay."""
import socket
from types import SimpleNamespace

import pytest

from skippercast.forecast import fetch
from skippercast.forecast.models import ECMWF_AWS, ECMWF_PORTAL, GFS_AWS
from skippercast.http import ContractError, Headers, HTTPStatusError

INVALID = 'Invalid forecast byte-range response'
SLICE = b'G' * 4  # bytes 100-103
URL = 'https://example.invalid/file.grib2'


class Session:
    """Answers each request from `answers` (a list, or a dict by URL) and records the calls."""

    def __init__(self, answers):
        self.answers = answers
        self.calls = []

    def request(self, method, url, headers=None, **options):
        self.calls.append((method, url, dict(headers or {})))
        answer = self.answers[url] if isinstance(self.answers, dict) else self.answers[len(self.calls) - 1]
        if isinstance(answer, BaseException):
            raise answer
        status, body, header_items = answer
        return SimpleNamespace(status=status, body=body, headers=Headers(header_items.items()))


def ranged(status=206, body=SLICE, content_range='bytes 100-103/1000', name='Content-Range'):
    return (status, body, {name: content_range} if content_range is not None else {})


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError('network access attempted')
    monkeypatch.setattr(socket, 'getaddrinfo', refuse)
    monkeypatch.setattr(socket, 'create_connection', refuse)
    monkeypatch.setattr(fetch, 'backoff', lambda retry: 0)


def get(answer, byte_range=(100, 103)):
    session = Session([answer])
    result = fetch.http(URL, byte_range, session=session)
    start, end = byte_range
    assert session.calls == [('GET', URL, {'Range': f'bytes={start}-' + ('' if end is None else str(end))})]
    return result


def refused(answer, byte_range=(100, 103)):
    with pytest.raises(ContractError) as caught:
        fetch.http(URL, byte_range, session=Session([answer]))
    assert str(caught.value) == INVALID


def test_bounded_range_requires_206_even_for_zero_start():
    assert get(ranged()) == SLICE
    assert get(ranged(body=b'ABCD', content_range='bytes 0-3/1000'), (0, 3)) == b'ABCD'
    refused(ranged(status=200, content_range=None))
    refused(ranged(status=200))  # 200 with a matching Content-Range and exact length
    refused(ranged(status=200, body=b'ABCD', content_range=None), (0, 3))
    refused(ranged(status=200, body=b'ABCD', content_range='bytes 0-3/4'), (0, 3))


@pytest.mark.parametrize('content_range', [
    None, 'bytes 101-104/1000', 'bytes 100-104/1000', 'bytes 100-102/1000', 'bytes 103-100/1000',
    'items 100-103/1000', 'bytes 100-103/103', 'bytes 100-103/50', 'bytes 100-103/abc',
    'bytes 100-103/1000 junk', 'junk bytes 100-103/1000', 'bytes 100-103/1000, 200-203/1000',
    'bytes -100-103/1000', 'bytes +100-103/1000', 'bytes */1000', 'bytes 100-/1000', '',
    'multipart/byteranges; boundary=x',
])
def test_content_range_must_match_requested_slice(content_range):
    refused(ranged(content_range=content_range))


@pytest.mark.parametrize('body', [b'GGG', b'GGGGG', b'', None])
def test_body_length_must_match_content_range(body):
    refused(ranged(body=body))


def test_content_range_header_name_case_and_whitespace():
    assert get(ranged(name='content-range')) == SLICE
    assert get(ranged(name='CONTENT-RANGE', content_range='  bytes 100-103/1000  ')) == SLICE
    assert get(ranged(content_range='bytes 100-103/*')) == SLICE  # bounded, unknown total


def test_open_ended_range_consistency():
    tail = b'T' * 900
    assert get(ranged(body=tail, content_range='bytes 100-999/1000'), (100, None)) == tail
    assert get(ranged(body=b'xyz', content_range='bytes 100-102/*'), (100, None)) == b'xyz'
    refused(ranged(body=tail, content_range='bytes 101-1000/1001'), (100, None))  # wrong start
    refused(ranged(body=b'xyz', content_range='bytes 100-102/1000'), (100, None))  # ends before known EOF
    refused(ranged(body=b'', content_range='bytes 100-99/1000'), (100, None))
    refused(ranged(body=b'', content_range='bytes 100-102/*'), (100, None))
    refused(ranged(status=200, body=tail, content_range=None), (100, None))


def test_nonrange_get_head_and_missing_files_unchanged():
    index = b'{"param": "10u"}'
    session = Session([(200, index, {})])
    assert fetch.http(URL, session=session) == index
    assert session.calls == [('GET', URL, {})]
    session = Session([(200, None, {})])
    assert fetch.http(URL, method='HEAD', session=session) == b''
    assert session.calls == [('HEAD', URL, {})]
    for status in (403, 404):
        assert fetch.http(URL, (0, 3), session=Session([HTTPStatusError('missing', status)])) is None
    with pytest.raises(HTTPStatusError):
        fetch.http(URL, (0, 3), session=Session([HTTPStatusError('server', 500)]))


def patch_session(monkeypatch, answers):
    session = Session(answers)
    monkeypatch.setattr(fetch, 'default_session', lambda: session)
    return session


ECMWF_FILE = '/20260927/00z/ifs/0p25/enfo/x.grib2'


def test_ecmwf_mirror_recovers_from_invalid_first_range(monkeypatch):
    first, second = ECMWF_AWS + ECMWF_FILE, ECMWF_PORTAL + ECMWF_FILE
    session = patch_session(monkeypatch, {first: ranged(status=200, content_range=None), second: ranged()})
    assert fetch.download_all([('u10', first, (100, 103))]) == {'u10': SLICE}
    assert [call[1] for call in session.calls] == [first, second]
    assert {call[2]['Range'] for call in session.calls} == {'bytes=100-103'}


def test_ecmwf_both_hosts_invalid_fails(monkeypatch):
    first, second = ECMWF_AWS + ECMWF_FILE, ECMWF_PORTAL + ECMWF_FILE
    session = patch_session(monkeypatch, {first: ranged(status=200), second: ranged(body=b'GG')})
    with pytest.raises(ContractError):
        fetch.download_all([('u10', first, (100, 103))])
    assert [call[1] for call in session.calls] == [first, second]


def test_noaa_invalid_range_never_succeeds(monkeypatch):
    noaa = GFS_AWS + '/gfs.20260927/00/atmos/gfs.t00z.pgrb2.0p25.f000'
    session = patch_session(monkeypatch, {noaa: ranged(status=200)})
    with pytest.raises(FileNotFoundError):
        fetch.download_all([('u10', noaa, (100, 103))])
    assert [call[1] for call in session.calls] == [noaa]  # no mirror for NOAA
    session = patch_session(monkeypatch, {noaa: ranged()})
    assert fetch.download_all([('u10', noaa, (100, 103))]) == {'u10': SLICE}
