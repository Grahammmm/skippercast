"""Published (preview/active) regions must not call themselves draft source-discovery packages."""
import json

import pytest

from tests._support import ROOT

FORBIDDEN = 'draft source-discovery'
SLUG = 'south-big-sur-san-simeon'
OPENING = 'South Big Sur\u2013San Simeon is a limited preview package.'
SUFFIX = (' Original grids, local coverage, legal access and exact routes'
          ' are not qualified for fishing targets.')
NEW_REASON = OPENING + SUFFIX
REASON_KEYS = {
    'groundtruth', 'kelp', 'surface-currents', 'subsurface-ocean', 'species-occurrence',
    'catch-effort', 'ais-history', 'harbor-access', 'wind-ensemble', 'wave-ensemble',
    'forecast-verification',
}
LEVELS = {'research': 13, 'partial': 10, 'missing': 1}


def forbidden_hits(region):
    """Return 'region field' diagnostics for forbidden wording in a published region."""
    if region.get('status') not in ('preview', 'active'):
        return []
    name = region.get('slug') or region.get('id') or '?'
    hits = []
    note = region.get('coverage_note')
    if note is not None:
        if not isinstance(note, str):
            hits.append(f'{name} coverage_note is not a string')
        elif FORBIDDEN in note.lower():
            hits.append(f'{name} coverage_note')
    for need, entry in (region.get('coverage') or {}).items():
        reason = entry.get('reason') if isinstance(entry, dict) else None
        if reason is None:
            continue
        if not isinstance(reason, str):
            hits.append(f'{name} coverage.{need}.reason is not a string')
        elif FORBIDDEN in reason.lower():
            hits.append(f'{name} coverage.{need}.reason')
    return hits


def test_preview_with_old_reason_fails():
    region = {'slug': 'x', 'status': 'preview',
              'coverage': {'kelp': {'level': 'research', 'reason': 'X is a Draft Source-Discovery package.'}}}
    assert forbidden_hits(region) == ['x coverage.kelp.reason']


def test_active_with_old_note_fails():
    assert forbidden_hits({'slug': 'y', 'status': 'active',
                           'coverage_note': 'A DRAFT source-discovery note'}) == ['y coverage_note']


def test_genuine_draft_allowed():
    assert forbidden_hits({'slug': 'd', 'status': 'draft',
                           'coverage_note': 'draft source-discovery package'}) == []


def test_near_misses_pass():
    region = {'slug': 'n', 'status': 'preview', 'coverage_note': 'limited preview; research-only, unqualified',
              'coverage': {'a': {'reason': 'draft plan text'}}}
    assert forbidden_hits(region) == []


def test_nonstring_reason_not_hidden():
    region = {'slug': 'z', 'status': 'preview', 'coverage': {'a': {'reason': ['draft source-discovery']}}}
    assert forbidden_hits(region) == ['z coverage.a.reason is not a string']


def test_malformed_json_is_visible(tmp_path):
    bad = tmp_path / 'region.json'
    bad.write_text('{not json')
    with pytest.raises(json.JSONDecodeError):
        json.loads(bad.read_text())


def _published_files():
    files = sorted((ROOT / 'regions').glob('*/region.json'))
    files += sorted((ROOT / 'dist' / 'regions').glob('*/region.json'))
    return files


@pytest.mark.parametrize('path', _published_files(), ids=lambda p: str(p.relative_to(ROOT)))
def test_no_published_region_says_draft_source_discovery(path):
    assert forbidden_hits(json.loads(path.read_text())) == []


def _south():
    return json.loads((ROOT / 'regions' / SLUG / 'region.json').read_text())


def test_south_big_sur_source_reasons_and_levels():
    region = _south()
    assert region['status'] == 'preview'
    coverage = region['coverage']
    changed = {k for k, v in coverage.items() if v.get('reason') == NEW_REASON}
    assert changed == REASON_KEYS
    levels = {}
    for entry in coverage.values():
        levels[entry['status']] = levels.get(entry['status'], 0) + 1
    assert levels == LEVELS
    for need in REASON_KEYS:
        assert coverage[need]['status'] in ('research', 'partial', 'missing')


def test_south_big_sur_compiled_text_matches_source():
    source = _south()['coverage']
    compiled = json.loads((ROOT / 'dist' / 'regions' / SLUG / 'region.json').read_text())
    report = json.loads((ROOT / 'dist' / 'regions' / SLUG / 'coverage.json').read_text())
    for need in REASON_KEYS:
        assert compiled['coverage'][need]['reason'] == NEW_REASON
        assert compiled['coverage'][need]['status'] == source[need]['status']
    assert FORBIDDEN not in json.dumps(report).lower()
    assert FORBIDDEN not in json.dumps(compiled).lower()
    assert NEW_REASON in json.dumps(report, ensure_ascii=False)
