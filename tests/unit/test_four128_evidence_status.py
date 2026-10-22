"""Admission's holds/status vetoes with all other evidence prerequisites valid."""
import json
from pathlib import Path

import pytest

from research.scripts import coastal_four128_admission as admission
from tests.audit_repro.test_research_four128_admission_evidence import _setup


def mutate_role(cfg, role, overrides):
    name = role + '.json'
    p = Path(cfg['evidence_root']) / name
    doc = json.loads(p.read_bytes())
    doc.update(overrides)
    raw = json.dumps(doc).encode()
    p.write_bytes(raw)
    (Path(cfg['staging_root']) / 'metadata' / name).write_bytes(raw)


@pytest.mark.parametrize('role', list(admission.DOCS))
@pytest.mark.parametrize('overrides,reason', [
    ({'holds': [], 'holds_added': ['unresolved']}, 'evidence held'),
    ({'holds': ['unresolved'], 'holds_added': []}, 'evidence held'),
    ({'holds': None}, 'evidence held'),
    ({'holds_added': ''}, 'evidence held'),
    ({'holds_added': {}}, 'evidence held'),
    ({'holds_added': False}, 'evidence held'),
    ({'status': 'REFUSED_SOURCE_RIGHTS_UNRESOLVED'}, 'evidence held or refused'),
    ({'status': 'refused_source_rights_unresolved'}, 'evidence held or refused'),
    ({'status': 'PASS_WITH_HOLD'}, 'evidence held or refused'),
    ({'status': 'PASS_REFUSED'}, 'evidence held or refused'),
])
def test_every_role_veto_is_independent(tmp_path, role, overrides, reason):
    cfg, now = _setup(tmp_path, {})
    assert set(admission.evidence_summary(cfg, now)) == set(admission.DOCS)
    mutate_role(cfg, role, overrides)
    with pytest.raises(ValueError, match=reason):
        admission.evidence_summary(cfg, now)


@pytest.mark.parametrize('status', ['PASS', 'PASS_EXPECTED_SOURCE_METADATA_GEOMETRY_STRICT_POLICY',
                                  admission.PARTIAL_SCIENCE_STATUS])
def test_existing_pass_vocabulary_is_preserved(tmp_path, status):
    cfg, now = _setup(tmp_path, {})
    mutate_role(cfg, 'independent-four128-scientific-preflight', {'status': status})
    assert admission.evidence_summary(cfg, now)['independent-four128-scientific-preflight']['status'] == status
