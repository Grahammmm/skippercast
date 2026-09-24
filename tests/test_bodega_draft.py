"""Keep the Bodega rollout from accidentally publishing an unreviewed legal claim."""
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_bodega_draft_has_local_salmon_boundary_and_no_approved_rules():
    region = json.loads((ROOT / 'regions/bodega-point-reyes/region.json').read_text())
    rules = json.loads((ROOT / 'dist/data/regulations-san-francisco.json').read_text())
    assert region['status'] == 'draft'
    north = next(area for area in region['map']['local_areas'] if area['id'] == 'bodega-north')
    assert north['bounds'][1] == 38 + 2 / 60
    assert any(item['id'] == 'salmon' for item in north['hidden_targets'])
    assert rules['rules_review_status'] == 'pending'
    assert not rules['species']
    assert rules['jurisdiction_id'] == region['jurisdiction_id']
    assert region['assets']['charters'] is None
