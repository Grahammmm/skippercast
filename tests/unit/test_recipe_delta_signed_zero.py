"""Signed zeros are distinct report values, not a raw JSON formatting diff."""

import json

import pytest

from tests.unit.test_sc_recipe_delta import pair
from scripts.coast_diagnostics import recipe_delta as delta


@pytest.mark.parametrize(
    ('before', 'after', 'changed'),
    [
        (0.0, -0.0, True),
        (-0.0, 0.0, True),
        (0.0, 0.0, False),
        (-0.0, -0.0, False),
        (0, 0.0, True),
    ],
)
@pytest.mark.parametrize('target', ['recipe', 'metadata'])
def test_zero_leaf_in_serialized_report(tmp_path, before, after, changed, target):
    paths = pair(tmp_path, right=('base', 'base'))
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    region = 'regions/morro-bay/region.json'
    for recipe, metadata, value in zip(paths[:2], paths[2:], (before, after), strict=True):
        # The validator binds the recipe bbox to the region bounds. Hold one
        # side of that binding constant so only the chosen leaf can change.
        for path, key, number in (
            (recipe, 'bbox', value if target == 'recipe' else 0.0),
            (metadata / region, 'bounds', value if target == 'metadata' else 0.0),
        ):
            document = json.loads(path.read_text())
            document[key][2] = number
            # Reformat the right snapshot in the otherwise unchanged cases.
            indent = 2 if changed or recipe == paths[0] else None
            path.write_text(json.dumps(document, indent=indent))

    report = json.loads(delta.serialize_report(delta.compare_recipes(*paths, workspace)))
    if not changed:
        assert report['status'] == 'UNCHANGED_REVIEW_REQUIRED'
        assert report['change_count'] == 0
        assert report['changes'] == []
        return

    assert report['status'] == 'CHANGED_REVIEW_REQUIRED'
    assert report['change_count'] == 1
    row, = report['changes']
    assert row['pointer'] == (
        '/recipe/bbox/2' if target == 'recipe' else '/metadata/regions~1morro-bay~1region.json/bounds/2'
    )
    assert row['before_present'] and row['after_present']
    # Decoded float equality alone would miss sign loss in the serialized row.
    assert json.dumps(row['before']) == json.dumps(before)
    assert json.dumps(row['after']) == json.dumps(after)
