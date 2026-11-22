"""Replay a documentation fixture against R8's read-only envelope verifier.

The notes check lives here: no packet or approval reader consumes this format.
"""
import pytest

from skippercast.relief import envelope, package, receipts
from tests._support import ROOT
from tests.unit.test_relief_package import SOURCE, assembly  # noqa: F401 (pytest fixture)

_NOTES = ROOT / 'docs/operations/fixtures/central-r8-review-notes.json'
_REGION = 'big-sur-coast'


@pytest.fixture
def review(tmp_path, assembly):  # noqa: F811
    # Fixed synthetic artifacts keep the example's envelope SHA independent of Git HEAD.
    root = tmp_path / _REGION
    generation = 'a' * 64
    layers = []
    for relative in sorted((package.ARCHIVE, package.DIGEST_ROOT)):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'synthetic layer bytes')
        layers.append(package.layer_record(root, relative))

    def write(relative, doc):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        raw = receipts.canonical(doc)
        path.write_bytes(raw)
        return {'path': relative, 'sha256': receipts.sha256_bytes(raw)}

    release = write(f'release/{generation}/release.json', {
        'schema': package.RELEASE_SCHEMA, 'generation': generation, 'code_sha': 'b' * 40,
        'region': _REGION, 'bounds': [-122, 35, -121, 36], 'minzoom': 8, 'maxzoom': 8,
        'private': False, 'disclaimer': package.DISCLAIMER, 'layers': layers,
        'digest_root_sha256': next(row['sha256'] for row in layers if row['path'] == package.DIGEST_ROOT),
        'sources': [{'id': SOURCE, 'attribution': 'Synthetic survey', 'rights_class': 'public',
                     'label': 'estimated', 'vertical_datum': 'NAVD88', 'survey_dates': ['2000'],
                     'rights': {'public_display': 'allowed', 'license': 'public-domain'}}],
        'detail_summary': {'mask': 'transparent-nodata', 'depth_bands': [
            {'source_id': SOURCE, 'min_depth_m': 0, 'max_depth_m': 20, 'resolution_m': 2, 'support_class': 2},
        ]},
        'native_support_by_zoom': {'8': {'tiles': 1, 'limit_m': 91.44, 'sources': []}},
    })
    qa = write(f'qa/{generation}/qa.json', {
        'status': 'PASS', 'release_sha256': release['sha256'], 'metrics': {'land_leak_pct': 0.0},
    })
    return root / write(f'review/{generation}/envelope.json', {
        'schema': envelope.ENVELOPE_SCHEMA, 'region': _REGION, 'generation': generation,
        'release': release, 'qa': qa, 'layers': layers,
    })['path']


def _closed_object(**properties):
    return {'type': 'object', 'required': list(properties), 'properties': properties, 'additionalProperties': False}


def _check_notes(notes, review):
    verified = envelope.verify_artifacts(review)
    text = {'type': 'string', 'pattern': r'\S'}
    observation = _closed_object(state={'enum': ['resolved', 'unresolved']}, note=text)
    package.validate_schema(notes, _closed_object(
        purpose=text,
        region={'const': verified.release['region']},
        envelope_sha256={'const': verified.envelope_sha256},
        observations=_closed_object(screenshot=observation, depth=observation, qa=observation),
    ))


def test_accepts_observation_notes_for_exact_envelope(review):
    """Catch fixture drift or collapsing the three evidence types into a single release status."""
    notes = package.decode_document(_NOTES.read_bytes())
    _check_notes(notes, review)
    observations = notes['observations'].values()
    assert {row['state'] for row in observations} == {'resolved', 'unresolved'}
    assert len({row['note'] for row in observations}) == 3


def test_refuses_neighbor_envelope_sha(review):
    """Same region and decoded envelope are not enough if notes cite different bytes."""
    notes = package.decode_document(_NOTES.read_bytes())
    neighbor_sha = receipts.sha256_bytes(review.read_bytes() + b'\n')
    with pytest.raises(package.ReleaseError, match=r'at envelope_sha256:'):
        _check_notes(notes | {'envelope_sha256': neighbor_sha}, review)


def test_refuses_wrong_region_with_matching_envelope_sha(review):
    """Catch routing a note to a different region merely because its digest matches."""
    notes = package.decode_document(_NOTES.read_bytes())
    with pytest.raises(package.ReleaseError, match=r'at region:'):
        _check_notes(notes | {'region': 'cambria-san-simeon'}, review)


def test_refuses_unexpected_verdict_for_exact_envelope(review):
    """Catch treating a copied packet verdict as an extra field in evidence-only notes."""
    notes = package.decode_document(_NOTES.read_bytes())
    verdict = f"APPROVED release {notes['region']} envelope={notes['envelope_sha256']}"
    with pytest.raises(package.ReleaseError, match=r"Additional properties.*'verdict'"):
        _check_notes(notes | {'verdict': verdict}, review)
