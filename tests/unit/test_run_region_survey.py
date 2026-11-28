"""The survey stages in the chain (Issue #3819): a pipeline release carries the survey detail and gap.

Live Morro v2 ships the survey-confidence detail and its no-survey gap companion. These tests pin how
run_region.py runs survey_detail and survey_gap after zone, how inventory lists their pairs and how
package takes them as upstream, and how --survey drops one or both for a region that has no gap.
"""
import argparse
import json

import pytest

from scripts.relief import region as region_cli
from scripts.relief import run_region as RR
from skippercast.relief import inventory, package, survey_delivery as sd
from tests.unit.test_relief_inventory_metadata import _bounds_archive, _inventory_ctx
from tests.unit.test_run_region import STAGE_ORDER, Box

DETAIL = [sd.DECODED_PATH, sd.WIRE_PATH]
GAP = [sd.GAP_DECODED_PATH, sd.GAP_WIRE_PATH]


@pytest.fixture
def box(tmp_path, monkeypatch):
    monkeypatch.delenv('SC_RELIEF_NORM', raising=False)
    monkeypatch.delenv('SC_RELIEF_OUT', raising=False)
    return Box(tmp_path)


def argv_of(box, stage):
    [call] = [call for call in box.calls() if call[0] == stage]
    return call


def upstream_of(call):
    return [call[i + 1] for i, arg in enumerate(call) if arg == '--upstream']


@pytest.mark.parametrize('survey, skipped, listed', [
    ('detail-and-gap', [], ['survey_detail:public', 'survey_gap:public']),
    ('detail', ['survey_gap'], ['survey_detail:public']),
    ('none', ['survey_detail', 'survey_gap'], []),
])
def test_survey_choice_sets_the_chain_inventory_and_package(box, survey, skipped, listed):
    # Bug caught: a release built by the chain without the survey layers live Morro ships (the old
    # chain), or a gap-less region forced through a survey_gap stage that holds.
    args = [] if survey == 'detail-and-gap' else ['--survey', survey]
    assert box.run(*args, through='package') == 0
    expected = [stage for stage in STAGE_ORDER[:STAGE_ORDER.index('package') + 2] if stage not in skipped]
    assert box.ran() == expected
    for stage in ('survey_detail', 'survey_gap'):
        if stage not in skipped:
            assert argv_of(box, stage)[5:] == ['--scope', 'public']
    inventory_args = argv_of(box, 'inventory')[5:]
    assert inventory_args == ([] if survey == 'none' else ['--survey', survey])
    assert upstream_of(argv_of(box, 'package')) == [
        'tiles:public', 'digests', 'zone:public', 'inventory', 'contours', *listed]


def test_region_config_is_not_forwarded_to_the_survey_stages(box, tmp_path):
    config = tmp_path / 'region.json'
    config.write_text('{}')
    assert box.run('--region-config', str(config), through='survey_gap') == 0
    assert '--region-config' in argv_of(box, 'zone')
    assert '--region-config' not in argv_of(box, 'survey_detail')
    assert '--region-config' not in argv_of(box, 'survey_gap')


@pytest.mark.parametrize('args, message', [
    (['--survey', 'detail', '--through', 'survey_gap'], '--survey detail skips survey_gap'),
    (['--survey', 'none', '--through', 'survey_detail'], '--survey none skips survey_detail'),
    (['--scope', 'private', '--through', 'survey_detail'], 'public-only survey stages'),
    (['--scope', 'private', '--through', 'inventory'], 'public-only survey stages'),
])
def test_unrunnable_survey_requests_are_usage_errors(box, capsys, args, message):
    with pytest.raises(SystemExit) as exc:
        RR.main(['morro-bay', '--out', str(box.out), *args], box.cfg)
    assert exc.value.code == 2 and message in capsys.readouterr().err
    assert box.calls() == [] and box.out_tree() == []


def test_private_scope_runs_when_the_chain_skips_the_survey_stages(box):
    assert box.run('--scope', 'private', through='zone') == 0
    assert box.run('--scope', 'private', '--survey', 'none', through='digests') == 0
    assert 'survey_detail' not in box.ran()


def test_dry_run_names_the_skipped_survey_stage(box, capsys):
    assert box.run('--survey', 'detail', '--dry-run', through='inventory') == 0
    text = capsys.readouterr().out
    assert 'not run: contours, nearshore_vectors, package, shots, qa, envelope' in text
    assert 'skipped (--survey): survey_gap' in text
    assert box.calls() == []


def survey_receipts(tmp_path, gap=True):
    docs = {}
    for key, pair in (('survey_detail.public', DETAIL), *((('survey_gap.public', GAP),) if gap else ())):
        for path in pair:
            (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
            (tmp_path / path).write_bytes(path.encode())
        docs[key] = {'outputs': [package.layer_record(tmp_path, path) for path in pair]}
    return docs


@pytest.mark.parametrize('gap', [True, False], ids=['detail-and-gap', 'detail'])
def test_inventory_lists_the_survey_pairs_its_survey_receipts_own(tmp_path, monkeypatch, gap):
    _bounds_archive(tmp_path / package.ARCHIVE, [-1.0, -1.0, 1.0, 1.0], header=(-1.0, -1.0, 1.0, 1.0))
    ctx = _inventory_ctx(tmp_path, monkeypatch)
    ctx.upstream.update(survey_receipts(tmp_path, gap))
    out = tmp_path / 'inventory'
    out.mkdir()
    inventory.build(ctx, out)
    paths = json.loads((out / inventory.MANIFEST).read_bytes())['layer_paths']
    assert [p for p in paths if sd.is_survey_path(p)] == sorted(DETAIL + (GAP if gap else []))
    # package's own shape rule accepts exactly these pairs
    survey = {p: package.layer_record(tmp_path, p) for p in paths if sd.is_survey_path(p)}
    assert set(sd.pointer_members(survey)) == ({'survey_detail', 'survey_gap'} if gap else {'survey_detail'})


def test_inventory_without_survey_upstream_lists_no_survey_layer(tmp_path, monkeypatch):
    _bounds_archive(tmp_path / package.ARCHIVE, [-1.0, -1.0, 1.0, 1.0], header=(-1.0, -1.0, 1.0, 1.0))
    ctx = _inventory_ctx(tmp_path, monkeypatch)
    survey_receipts(tmp_path)  # files on disk, but no survey receipt taken as upstream
    out = tmp_path / 'inventory'
    out.mkdir()
    inventory.build(ctx, out)
    paths = json.loads((out / inventory.MANIFEST).read_bytes())['layer_paths']
    assert not any(sd.is_survey_path(p) for p in paths)


@pytest.mark.parametrize('change', ['extra file', 'missing wire'])
def test_inventory_refuses_a_survey_receipt_that_does_not_own_exactly_its_pair(tmp_path, monkeypatch, change):
    _bounds_archive(tmp_path / package.ARCHIVE, [-1.0, -1.0, 1.0, 1.0], header=(-1.0, -1.0, 1.0, 1.0))
    ctx = _inventory_ctx(tmp_path, monkeypatch)
    docs = survey_receipts(tmp_path)
    rows = docs['survey_detail.public']['outputs']
    if change == 'extra file':
        rows.append({**rows[0], 'path': sd.PREFIX + 'other.geojson'})
    else:
        del rows[1]
    ctx.upstream.update(docs)
    out = tmp_path / 'inventory'
    out.mkdir()
    with pytest.raises(inventory.InventoryError, match='survey_detail.public receipt does not own exactly'):
        inventory.build(ctx, out)
    assert not (out / inventory.MANIFEST).exists()


@pytest.mark.parametrize('survey, refs', [
    (None, list(inventory.UPSTREAM)),
    ('detail', [*inventory.UPSTREAM, 'survey_detail:public']),
    ('detail-and-gap', [*inventory.UPSTREAM, 'survey_detail:public', 'survey_gap:public']),
])
def test_region_cli_takes_inventory_upstream_from_its_survey_option(tmp_path, monkeypatch, survey, refs):
    # The receipt's upstream edges (and so the done rule and the generation) follow --survey.
    seen = []

    class Result:
        exit_code = 0

        def line(self):
            return 'ok'

    monkeypatch.setattr(region_cli.receipts, 'run_stage', lambda run: seen.append(run) or Result())
    argv = ['--region', 'test-bay', '--out', str(tmp_path), *(['--survey', survey] if survey else [])]
    assert region_cli.run_module('inventory', inventory, argv) == 0
    [run] = seen
    assert [ref.key for ref in run.upstream] == [region_cli.receipts.Ref.parse(text).key for text in refs]


def test_inventory_survey_option_choices():
    parser = argparse.ArgumentParser()
    inventory.add_arguments(parser)
    with pytest.raises(SystemExit):
        parser.parse_args(['--survey', 'gap'])
    assert inventory.upstream(parser.parse_args([])) == inventory.UPSTREAM
