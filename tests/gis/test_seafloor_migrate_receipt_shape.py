"""Numeric cache migration names a malformed run/physical receipt before any recovery step.

Contract: `migrate_numeric_cache` reads the reach's run.json and physical.json and, if either is not the
expected shape, raises the module's `Incomplete or inconsistent original cache identity` ValueError rather
than a bare TypeError/KeyError; an absent file stays an honest FileNotFoundError.
Only temp roots and synthetic receipts: no migration, backup or rename is run.
"""
import json

import pytest

from skippercast.seafloor.adopt import digest
from skippercast.seafloor.migrate_cache import migrate_numeric_cache

REACH = 'shape-r01'
IDENTITY = 'Incomplete or inconsistent original cache identity'
ABSENT = object()  # file not written at all (JSON null is a legitimate bad value, so None cannot mean absent)


def _good():
    """A well-shaped, self-consistent receipt pair with an empty output inventory."""
    inputs = {'reach_id': REACH}
    run = {'inputs': inputs, 'outputs': {}, 'ledger_summary': {},
           'physical_input_hash': digest(inputs), 'input_hash': digest(inputs)}
    return run, {'input_hash': digest(inputs), 'outputs': {}}


def _root(tmp_path, monkeypatch, run, physical):
    monkeypatch.delenv('SKIPPERCAST_SOURCE_SCOPE', raising=False)
    folder = tmp_path/'var/seafloor/reaches'/REACH
    folder.mkdir(parents=True)
    if run is not ABSENT:
        (folder/'run.json').write_text(json.dumps(run))
    if physical is not ABSENT:
        (folder/'physical.json').write_text(json.dumps(physical))
    return tmp_path


def _run_variant(**change):
    run, _ = _good()
    for key, value in change.items():
        if value is KeyError:
            del run[key]
        else:
            run[key] = value
    return run


def _physical_variant(**change):
    _, physical = _good()
    for key, value in change.items():
        if value is KeyError:
            del physical[key]
        else:
            physical[key] = value
    return physical


# Bug caught: indexing receipt['inputs'] etc. raises TypeError (list/null/string receipt) or KeyError
# (missing field), or a wrong-typed field slips through to a later bare error.
BAD_RUNS = [
    pytest.param([], id='run-list'),
    pytest.param(None, id='run-null'),
    pytest.param('run', id='run-string'),
    pytest.param({}, id='run-empty-object'),
    pytest.param(_run_variant(inputs=KeyError), id='run-no-inputs'),
    pytest.param(_run_variant(inputs=[]), id='run-inputs-list'),
    pytest.param(_run_variant(outputs=KeyError), id='run-no-outputs'),
    pytest.param(_run_variant(outputs=[]), id='run-outputs-list'),
    pytest.param(_run_variant(ledger_summary=KeyError), id='run-no-ledger-summary'),
    pytest.param(_run_variant(ledger_summary='done'), id='run-ledger-summary-string'),
    pytest.param(_run_variant(physical_input_hash=KeyError), id='run-no-physical-input-hash'),
    pytest.param(_run_variant(physical_input_hash=7), id='run-physical-input-hash-int'),
    pytest.param(_run_variant(input_hash=KeyError), id='run-no-input-hash'),
    pytest.param(_run_variant(input_hash=None), id='run-input-hash-null'),
]

# Bug caught: physical.json shape errors surface as bare TypeError/KeyError instead of the named refusal.
BAD_PHYSICALS = [
    pytest.param([], id='physical-list'),
    pytest.param(None, id='physical-null'),
    pytest.param({}, id='physical-empty-object'),
    pytest.param(_physical_variant(input_hash=KeyError), id='physical-no-input-hash'),
    pytest.param(_physical_variant(input_hash=5), id='physical-input-hash-int'),
    pytest.param(_physical_variant(outputs=KeyError), id='physical-no-outputs'),
    pytest.param(_physical_variant(outputs=[]), id='physical-outputs-list'),
]


@pytest.mark.parametrize('run', BAD_RUNS)
def test_malformed_run_receipt_is_refused_by_name(tmp_path, monkeypatch, run):
    _, physical = _good()
    root = _root(tmp_path, monkeypatch, run, physical)
    with pytest.raises(ValueError) as refused:
        migrate_numeric_cache(REACH, root=root)
    assert str(refused.value) == IDENTITY


@pytest.mark.parametrize('physical', BAD_PHYSICALS)
def test_malformed_physical_receipt_is_refused_by_name(tmp_path, monkeypatch, physical):
    run, _ = _good()
    root = _root(tmp_path, monkeypatch, run, physical)
    with pytest.raises(ValueError) as refused:
        migrate_numeric_cache(REACH, root=root, apply=True)
    assert str(refused.value) == IDENTITY


# Bug caught: the shape check is so strict (or placed so late/early) that a legitimate receipt is refused
# as an identity problem; this well-formed, self-consistent pair must pass the check and be stopped only
# by the next, unrelated guard (output inventory), proving the check refuses shape and nothing else.
def test_well_formed_receipt_passes_the_shape_check(tmp_path, monkeypatch):
    run, physical = _good()
    root = _root(tmp_path, monkeypatch, run, physical)
    with pytest.raises(ValueError) as refused:
        migrate_numeric_cache(REACH, root=root)
    assert str(refused.value) == 'Incomplete output inventory'


# Bug caught: a shape check that swallows or rewrites a missing file as the identity error (or reads
# only one file), hiding that the cache folder is absent/incomplete.
@pytest.mark.parametrize('present', ['run', 'physical', 'neither'])
def test_missing_receipt_file_stays_file_not_found(tmp_path, monkeypatch, present):
    run, physical = _good()
    root = _root(tmp_path, monkeypatch, run if present == 'run' else ABSENT,
                 physical if present == 'physical' else ABSENT)
    with pytest.raises(FileNotFoundError):
        migrate_numeric_cache(REACH, root=root)
