"""F31-06: duplicate mirror URLs must not silently lose publisher checksums."""

import pytest

from research.scripts.enumerate_coast_prefetch import reconcile

URL = 'https://mirror.example.test/tile.tiff'
CURRENT_SHA = 'b' * 64
CURRENT = {'source': 'noaa-bluetopo', 'url': URL, 'bytes': 12,
           'sha256': CURRENT_SHA, 'segments': ['C1', 'C2'],
           'evidence': 'https://mirror.example.test/current-scheme.gpkg',
           'etag': 'current-etag', 'licence': 'Synthetic fixture'}


@pytest.mark.parametrize('old_sha', [None, CURRENT_SHA], ids=['unknown-old', 'matching-pins'])
def test_current_checksum_stays_runnable(old_sha):
    # A known current pin is neither erased by an unknown old one nor held when they agree.
    old = {**CURRENT, 'sha256': old_sha, 'segments': ['C1'], 'evidence': 'seed-receipt'}
    plan = reconcile({'files': [old], 'unresolved': []}, {'files': [], 'unresolved': []},
                     None, ([CURRENT], [], {}))

    assert plan['files'] == [CURRENT]
    assert plan['unresolved'] == []


def test_equal_size_checksum_conflict_is_held_out_of_partial_plan():
    # Equal size doesn't prove byte identity. Partial prefetch iterates every row in files.
    old = {**CURRENT, 'source': 'bluetopo-ca', 'sha256': 'a' * 64,
           'evidence': 'seed-receipt', 'etag': 'old-etag', 'segments': ['C1']}
    other = {**CURRENT, 'url': 'https://mirror.example.test/other-tile.tiff'}
    plan = reconcile({'files': [old], 'unresolved': []}, {'files': [], 'unresolved': []},
                     None, ([CURRENT, other], [], {}))

    assert plan['files'] == [other]
    hold, = plan['unresolved']
    assert hold['url'] == URL
    assert hold['previous'] == old
    assert hold['observed'] == [CURRENT]
