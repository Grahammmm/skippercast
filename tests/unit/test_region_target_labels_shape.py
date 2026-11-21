"""The region compiler must handle label shapes without JSON Schema validation."""

import pytest

from skippercast.platform.build import target_options


TARGETS = {
    'cod': {'name': 'Cod'},
    'perch': {'name': 'Perch'},
}


@pytest.mark.parametrize('labels', [None, ['cod'], 'cod'], ids=['null', 'list', 'string'])
def test_non_object_target_labels_name_the_field(labels):
    # Without a shape guard, set(labels) or labels.values() treats these as objects.
    region = {'species': ['cod', 'perch'], 'target_labels': labels}
    with pytest.raises(ValueError, match=r'\btarget_labels\b'):
        target_options(region, TARGETS)


def test_omitted_target_labels_use_catalog_names():
    # Checking the type must not turn an optional field into a required one.
    assert target_options({'species': ['cod', 'perch']}, TARGETS) == [
        {'id': 'cod', 'name': 'Cod'},
        {'id': 'perch', 'name': 'Perch'},
    ]


def test_target_labels_override_only_the_named_target():
    # A valid object still overrides the named target, not its unlabelled neighbour.
    region = {'species': ['cod', 'perch'], 'target_labels': {'cod': 'Local Cod'}}
    assert target_options(region, TARGETS) == [
        {'id': 'cod', 'name': 'Local Cod'},
        {'id': 'perch', 'name': 'Perch'},
    ]
