"""fetch_source refuses a malformed manifest row by name, never with TypeError or KeyError.

Contract: every refusal at the original-source door is a named ValueError (the missing-source
FileNotFoundError for a healthy, uncached row is unchanged). No network: ``fetch=False``.
"""
import hashlib

import pytest

from skippercast.seafloor.fetch import (
    COMPILATION_PREFIXES, canonical_source_url, compilation_source, fetch_source)

URL = 'https://cmgds.marine.usgs.gov/data/survey/original.zip'
PAYLOAD = b'synthetic original bytes'
DIGEST = hashlib.sha256(PAYLOAD).hexdigest()
MISSING_KEYS = 'Source row needs url, sha256 and bytes'
GOOD = {'url': URL, 'sha256': 'a' * 64, 'bytes': 10}


def without(row, key):
    return {k: v for k, v in row.items() if k != key}


@pytest.mark.parametrize('key', ['url', 'sha256', 'bytes'])
def test_absent_key_is_a_named_refusal(tmp_path, key):
    # Bug caught: row[key] indexing leaks KeyError('<key>') instead of one named refusal.
    with pytest.raises(ValueError, match=MISSING_KEYS):
        fetch_source(without(GOOD, key), tmp_path / 'cache')


def test_empty_row_is_the_same_named_refusal(tmp_path):
    # Bug caught: only the first indexed key is checked, so an empty row still raises KeyError.
    with pytest.raises(ValueError, match=MISSING_KEYS):
        fetch_source({}, tmp_path / 'cache')


@pytest.mark.parametrize('checksum', [None, 7, b'a' * 64, ['a' * 64]])
def test_non_string_checksum_is_invalid_checksum(tmp_path, checksum):
    # Bug caught: re.fullmatch on a non-string leaks TypeError('expected string or bytes-like object').
    with pytest.raises(ValueError, match='^Invalid source checksum$'):
        fetch_source(dict(GOOD, sha256=checksum), tmp_path / 'cache')


@pytest.mark.parametrize('checksum', ['A' * 64, 'a' * 63, 'unknowN', ''])
def test_malformed_string_checksum_still_invalid(tmp_path, checksum):
    # Bug caught: the non-string guard replaces the regex instead of sitting beside it.
    with pytest.raises(ValueError, match='^Invalid source checksum$'):
        fetch_source(dict(GOOD, sha256=checksum), tmp_path / 'cache')


def test_existing_refusals_keep_their_order(tmp_path):
    # Bug caught: the new row-shape checks run ahead of the URL refusals and mask them.
    with pytest.raises(ValueError, match='not in canonical form'):
        fetch_source(dict(GOOD, url=None, sha256=None), tmp_path / 'cache')
    with pytest.raises(ValueError, match='^Unreviewed original-source URL$'):
        fetch_source(dict(GOOD, url='https://example.com/a.zip', sha256=None), tmp_path / 'cache')
    with pytest.raises(ValueError, match='^Invalid source checksum$'):
        fetch_source(dict(GOOD, url=URL.replace('original.zip', 'original.txt'), sha256=None),
                     tmp_path / 'cache')
    with pytest.raises(ValueError, match='^Unsupported source container$'):
        fetch_source(dict(GOOD, url=URL.replace('original.zip', 'original.txt')), tmp_path / 'cache')


@pytest.mark.parametrize('row', [GOOD, dict(GOOD, bytes='unknown'), dict(GOOD, sha256='unknown')])
def test_complete_uncached_row_reaches_missing_source(tmp_path, row):
    # Control: a healthy row is untouched and reaches the same FileNotFoundError as before.
    with pytest.raises(FileNotFoundError, match='^Original source missing; use --fetch or --local$'):
        fetch_source(row, tmp_path / 'cache')


def cached(tmp_path):
    destination = tmp_path / 'cache' / DIGEST / 'source.zip'
    destination.parent.mkdir(parents=True)
    destination.write_bytes(PAYLOAD)
    return destination


def test_cache_hit_byte_count_check_is_unchanged(tmp_path):
    # Bug caught: relaxing the cached-file byte check (or reading bytes with a lenient default).
    destination = cached(tmp_path)
    row = {'url': URL, 'sha256': DIGEST, 'bytes': len(PAYLOAD)}
    assert fetch_source(row, tmp_path / 'cache') == (destination, False)
    assert fetch_source(dict(row, bytes='unknown'), tmp_path / 'cache') == (destination, False)
    with pytest.raises(ValueError, match='^Cached original byte count mismatch$'):
        fetch_source(dict(row, bytes=len(PAYLOAD) + 1), tmp_path / 'cache')


def test_cached_file_with_absent_bytes_is_refused_by_name(tmp_path):
    # Bug caught: reading ``bytes`` with .get so a row whose bytes is legitimately absent turns the
    # cached-file check into a different error (None != size) or silently skips it.
    cached(tmp_path)
    with pytest.raises(ValueError, match=MISSING_KEYS):
        fetch_source({'url': URL, 'sha256': DIGEST}, tmp_path / 'cache')


@pytest.mark.parametrize('value', [None, 5, b'https://x/', ['https://x/']])
def test_compilation_source_refuses_non_strings(value):
    # Bug caught: .startswith on a non-string leaks AttributeError, unlike canonical_source_url.
    assert compilation_source(value) is False
    assert canonical_source_url(value) is False


def test_compilation_source_still_matches_reviewed_prefixes():
    # Bug caught: the non-string guard also returns False for real compilation products.
    assert compilation_source(COMPILATION_PREFIXES[0] + 'x.tif') is True
    assert compilation_source(URL) is False
