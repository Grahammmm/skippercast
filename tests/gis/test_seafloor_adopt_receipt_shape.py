"""Private-physics adoption names a malformed run receipt before it compares anything.

Contract: `_adopt_staged` checks the shape of the staged run.json and physical.json
first and raises a named ValueError (not a bare TypeError/KeyError), writes nothing,
and leaves every existing refusal for a well-formed receipt unchanged.
"""
import json

import pytest

pytest.importorskip('pyproj')
pytest.importorskip('shapely')
from skippercast.seafloor import adopt  # noqa: E402

OUTPUT_NAMES = adopt.OUTPUTS
RUN_MALFORMED = r'^Private run receipt is malformed$'
PHYSICAL_MALFORMED = r'^Private physical receipt is malformed$'
INVENTORY = r'^Private output inventory is incomplete$'


def good_run(**changes):
    # Wrong output inventory on purpose: a shape check that runs late would
    # report the inventory instead of the malformed field.
    run = {'inputs': {'reach_id': 'r1'}, 'outputs': {}, 'ledger_summary': {},
           'physical_input_hash': 'abc', 'publication_prohibited': True}
    run.update(changes)
    return run


def good_physical(**changes):
    physical = {'input_hash': 'abc', 'outputs': {}}
    physical.update(changes)
    return physical


def without(document, key):
    return {k: v for k, v in document.items() if k != key}


ABSENT = object()


def stage(tmp_path, run, physical=ABSENT):
    staging = tmp_path / 'staging'
    staging.mkdir()
    (staging / 'run.json').write_text(json.dumps(run))
    if physical is not ABSENT:
        (staging / 'physical.json').write_text(json.dumps(physical))
    return staging


def call(tmp_path, staging):
    destination = tmp_path / 'reaches' / 'r1'
    return adopt._adopt_staged('r1', tmp_path, {'reaches': []}, tmp_path / 'private', staging, destination)


def snapshot(tmp_path):
    return {str(p.relative_to(tmp_path)): p.read_bytes() if p.is_file() else None
            for p in sorted(tmp_path.rglob('*'))}


@pytest.fixture
def no_hash_no_write(monkeypatch):
    """Any hash, digest or JSON write before the shape check passes fails the test."""
    def forbidden(*args, **kwargs):
        raise AssertionError('hashed or wrote before the receipt shape was checked')
    for name in ('sha256', 'digest', 'atomic_json'):
        monkeypatch.setattr(adopt, name, forbidden)


# Bug caught: indexing the receipt directly, so a list/null/empty/short receipt
# surfaces as TypeError/KeyError instead of the module's named refusal.
RUN_CASES = {
    'list': [],
    'string': 'receipt',
    'null': None,
    'empty object': {},
    'no inputs': without(good_run(), 'inputs'),
    'no outputs': without(good_run(), 'outputs'),
    'no ledger_summary': without(good_run(), 'ledger_summary'),
    'no physical_input_hash': without(good_run(), 'physical_input_hash'),
    'inputs list': good_run(inputs=[]),
    'outputs null': good_run(outputs=None),
    'ledger_summary string': good_run(ledger_summary='done'),
    'physical_input_hash number': good_run(physical_input_hash=7),
}


@pytest.mark.parametrize('run', RUN_CASES.values(), ids=RUN_CASES)
def test_malformed_run_receipt_is_named_and_nothing_is_written(tmp_path, no_hash_no_write, run):
    staging = stage(tmp_path, run, good_physical())
    before = snapshot(tmp_path)
    with pytest.raises(ValueError, match=RUN_MALFORMED):
        call(tmp_path, staging)
    assert snapshot(tmp_path) == before
    assert not (tmp_path / 'reaches').exists()


# Bug caught: physical.json read only after the checksum loop and indexed bare,
# or its shape checked after the run.json inventory/checksum comparisons.
PHYSICAL_CASES = {
    'list': [],
    'null': None,
    'empty object': {},
    'no input_hash': without(good_physical(), 'input_hash'),
    'no outputs': without(good_physical(), 'outputs'),
    'input_hash number': good_physical(input_hash=1),
    'outputs list': good_physical(outputs=[]),
}


@pytest.mark.parametrize('physical', PHYSICAL_CASES.values(), ids=PHYSICAL_CASES)
def test_malformed_physical_receipt_is_named_and_nothing_is_written(tmp_path, no_hash_no_write, physical):
    staging = stage(tmp_path, good_run(), physical)
    before = snapshot(tmp_path)
    with pytest.raises(ValueError, match=PHYSICAL_MALFORMED):
        call(tmp_path, staging)
    assert snapshot(tmp_path) == before
    assert not (tmp_path / 'reaches').exists()


# Bug caught: the new check swallowing or reordering the existing inventory
# refusal for a dict receipt that is merely wrong, with or without physical.json.
@pytest.mark.parametrize('physical', [good_physical(), ABSENT], ids=['with physical.json', 'without physical.json'])
def test_wrong_inventory_control_keeps_its_existing_message(tmp_path, physical):
    staging = stage(tmp_path, good_run(), physical)
    with pytest.raises(ValueError, match=INVENTORY):
        call(tmp_path, staging)


def stage_checked(tmp_path, ledger_summary):
    """A well-formed receipt whose output checksums are real; physical outputs wrong."""
    staging = tmp_path / 'staging'
    staging.mkdir()
    inputs = {'reach_id': 'r1'}
    for name in OUTPUT_NAMES:
        (staging / name).write_text(json.dumps({'name': name}))
    # physical.json is itself a checksummed output: write it before hashing.
    (staging / 'physical.json').write_text(json.dumps(
        {'input_hash': adopt.digest(inputs), 'outputs': {}}))
    outputs = {name: adopt.sha256(staging / name) for name in OUTPUT_NAMES}
    run = {'inputs': inputs, 'outputs': outputs, 'ledger_summary': ledger_summary,
           'physical_input_hash': adopt.digest(inputs), 'publication_prohibited': True}
    (staging / 'run.json').write_text(json.dumps(run))
    return staging


# Bug caught: a shape check that demands a truthy ledger_summary.processing_incomplete
# wrongly refuses a valid receipt whose value is null (or absent); the run must get
# past the shape and the incompleteness gate to the later physical-inventory refusal.
@pytest.mark.parametrize('ledger_summary', [{'processing_incomplete': None}, {'processing_incomplete': False}, {}],
                         ids=['null', 'false', 'absent'])
def test_valid_receipt_with_unset_processing_incomplete_is_not_refused_as_malformed(tmp_path, ledger_summary):
    staging = stage_checked(tmp_path, ledger_summary)
    with pytest.raises(ValueError, match=INVENTORY):
        call(tmp_path, staging)


# Control, unaffected by the shape check: a set processing_incomplete is still refused
# by the existing guard with its existing message (the guard was not loosened).
def test_processing_incomplete_true_keeps_its_existing_refusal(tmp_path):
    staging = stage_checked(tmp_path, {'processing_incomplete': True})
    with pytest.raises(ValueError, match=r'^Private physics receipt is incomplete or inconsistent$'):
        call(tmp_path, staging)
