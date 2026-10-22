"""Synthetic integration coverage for deep-datum warnings and their negative control."""
from datetime import datetime, timezone

import numpy as np
import pytest

from skippercast.coastal import vertical
from skippercast.coastal.handoff.common import ref, write
from skippercast.coastal.render import terrain_only
from tests.audit_repro import test_render_deep_datum_disclaimer as deep_repro
from tests.audit_repro.test_render_terrain_triangulation import normalized_terrain

NOW = datetime(2026, 10, 22, tzinfo=timezone.utc)


def accepted(root, document):
    """Attach a synthetic independent attestation through the real verify path."""
    document = dict(document)
    document.pop('uncertainty_kind', None)
    document.update(support_kind='derived_valid_sample_support', source_accessed=False,
                    imagery_used=False, internal_diagnostic=True,
                    publication_prohibited=True, website='held', habitat='unassessed')
    review = dict(schema=terrain_only.REVIEW, scope='internal-terrain-only-scientific-review',
                  facts_digest=terrain_only.context(document), independent=True,
                  reviewer_id='synthetic-independent-reviewer', decision='accept',
                  checked_at='2026-10-21T00:00:00Z', valid_until='2026-10-24T00:00:00Z',
                  holds_added=[], synthetic=True)
    write(root/'science-review.json', review)
    document['scientific_review'] = ref(root, 'science-review.json', terrain_only.REVIEW)
    write(root/'input.json', document)
    return ref(root, 'input.json', terrain_only.INPUT)


@pytest.mark.parametrize('datum', sorted(vertical.DEEP_DATUMS))
def test_deep_warning_survives_png_and_receipt(tmp_path, monkeypatch, datum):
    monkeypatch.setattr(deep_repro, 'DATUM', datum)
    _, xx = np.indices((8, 8))
    document = deep_repro.deep_terrain(tmp_path, 120.0 + xx)
    acceptance = accepted(tmp_path, document)
    result = terrain_only.preview(tmp_path, acceptance, output_dir='preview', now=NOW)
    mesh = terrain_only.build_terrain(tmp_path, document)
    rendered, pixels = terrain_only.render_terrain(mesh, None, terrain_only.style_controls())
    legends = rendered['image_legends']
    warning = next(row for row in legends if 'NOT FOR NAVIGATION' in row['text'])
    note = next(row for row in legends if row['text'] == vertical.DEEP_DATUM_NOTES[datum])
    # Verify actual bitmap glyphs, not only the accompanying legend metadata.
    for row in (warning, note):
        expected = np.full_like(pixels, [238, 243, 246])
        terrain_only.text(expected, row['x'], row['y'], row['text'], row['scale'])
        glyphs = (expected == [22, 31, 39]).all(axis=2)
        assert glyphs.any()
        assert np.array_equal(pixels[glyphs], expected[glyphs])
        assert row['x'] + len(row['text'])*4*row['scale'] <= terrain_only.WIDTH
    assert any('NOT FOR NAVIGATION' in item and vertical.DEEP_DATUM_NOTES[datum] in item
               for item in result['limitations'])
    assert result['vertical']['deep_datum'] == document['vertical']['deep_datum']
    assert result['publication_prohibited'] and result['website'] == 'held'
    assert terrain_only.preview(tmp_path, acceptance, output_dir='preview', now=NOW) == result


def test_chart_datum_does_not_get_a_deep_datum_caveat(tmp_path):
    depth = np.full((4, 4), 20.0)
    document = normalized_terrain(tmp_path, depth, np.ones(depth.shape, bool))
    result = terrain_only.preview(tmp_path, accepted(tmp_path, document), output_dir='preview', now=NOW)
    assert not any('DATUM OFFSET UNBOUNDED' in item['text'] for item in result['image_legends'])
    assert not any('datum offset unbounded' in item for item in result['limitations'])
    assert 'deep_datum' not in result['vertical']
