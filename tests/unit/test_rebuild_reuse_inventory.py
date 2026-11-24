"""Exercise the inventory CLI against real, synthetic stage receipt history."""
import json

import pytest

from scripts.relief import rebuild_reuse_inventory as cli
from skippercast.relief import receipts


@pytest.fixture
def stage_history(tmp_path):
    region = receipts.Region(tmp_path, 'fixture')

    def produce(stage, version, *, scope=None, upstream=()):
        def build(target):
            (target / 'payload').write_bytes(b'original')

        result = receipts.run_stage(receipts.StageRun(
            region, stage, build, 'a' * 64, scope=scope, upstream=upstream,
            plan=receipts.Plan(params={'version': version}), target='artifacts/{stage}/{generation}',
        ), host=lambda _: {}, repo_sha=lambda: None)
        assert result.state == 'ok', result.reason
        return result.generation

    source = produce('source', 1)
    produce('dependency', 1, scope='public', upstream=(receipts.Ref('source'),))
    upstream = (receipts.Ref('dependency', 'public'),)
    saved = produce('example', 1, scope='public', upstream=upstream)
    current = produce('example', 2, scope='public', upstream=upstream)
    path = region.receipt_path('example', 'public')
    return region, produce, path, source, saved, current


@pytest.fixture
def report(monkeypatch, capsys):
    def run(region, *, error=False):
        writes = []

        def intercept(*args, **kwargs):
            writes.append(args)
            raise AssertionError('inventory attempted a receipt write or stage lock')

        with monkeypatch.context() as guard:
            guard.setattr(receipts, 'write_json_atomic', intercept)
            guard.setattr(receipts, '_flock', intercept)
            args = ['--out', str(region.out_root), region.id, 'example:public']
            if error:
                with pytest.raises(SystemExit) as exc:
                    cli.main(args)
                assert exc.value.code == 2
            else:
                assert cli.main(args) == 0
        assert writes == []
        captured = capsys.readouterr()
        return captured if error else json.loads(captured.out)

    return run


def test_intact_history_is_distinct_from_current(stage_history, report):
    # A current-generation mirror and an unreadable sibling must not leak in:
    # a report that treats all map entries as prior or scans other scopes fails.
    region, _, path, _, saved, current = stage_history
    doc = receipts.read_receipt(path)
    assert doc is not None
    doc['generation_history'][current] = {k: v for k, v in doc.items() if k != 'generation_history'}
    receipts.write_json_atomic(path, doc)
    region.receipt_path('example', 'private').write_text('not JSON', encoding='utf-8')
    before = path.read_bytes(), path.stat().st_mtime_ns

    assert report(region) == {
        'region': 'fixture', 'stage': 'example.public',
        'current': {'generation': current, 'receipt_status': 'ok'},
        'reusable_history': [{'generation': saved, 'output_count': 1}],
    }
    assert (path.read_bytes(), path.stat().st_mtime_ns) == before


@pytest.mark.parametrize('change', ['same-size-changed-bytes', 'missing-output', 'wrong-target'])
def test_saved_output_identity_is_required(stage_history, report, change):
    # A digest-only check can mistake the current generation's byte-identical
    # payload for a saved output of a prior generation.
    region, _, path, _, saved, current = stage_history
    doc = receipts.read_receipt(path)
    assert doc is not None
    prior = doc['generation_history'][saved]
    evidence = prior['outputs'][0]
    output = region.resolve(evidence['path'])
    if change == 'wrong-target':
        assert report(region)['reusable_history'] == [{'generation': saved, 'output_count': 1}]
        foreign = doc['outputs'][0]
        assert output.parent == region.resolve(prior['target'])
        assert region.resolve(foreign['path']).parent == region.resolve(doc['target']) != output.parent
        assert region.resolve(foreign['path']).read_bytes() == output.read_bytes()
        evidence['path'] = foreign['path']
        receipts.write_json_atomic(path, doc)
    elif change == 'same-size-changed-bytes':
        output.write_bytes(b'modified')
        assert output.stat().st_size == evidence['bytes']
    else:
        output.unlink()

    result = report(region)
    assert result['current']['generation'] == current
    assert result['reusable_history'] == []


def test_stale_upstream_generation_is_excluded_even_with_intact_bytes(stage_history, report):
    # Rebuilding a dependency with the same output bytes still changes its identity;
    # its old intact history is not a substitute for the current dependency receipt.
    region, produce, _, _, _, _ = stage_history
    produce('dependency', 2, scope='public', upstream=(receipts.Ref('source'),))
    assert receipts.check(region, 'dependency', 'public').done
    assert report(region)['reusable_history'] == []


def test_matching_upstream_generations_must_be_recursively_done(stage_history, report):
    # Comparing the immediate generation alone would accept a broken ancestor.
    # An interrupted ancestor also must not make this reader take a stage lock.
    region, _, _, source, _, _ = stage_history
    path = region.receipt_path('source')
    doc = receipts.read_receipt(path)
    assert doc is not None
    assert doc['generation'] == source and region.lock_path('source').exists()
    receipts.write_json_atomic(path, dict(doc, status='failed', error=receipts.INTERRUPTED))
    assert report(region)['reusable_history'] == []


@pytest.mark.parametrize('defect', ['held', 'no-output-identities', 'wrong-generation-key'])
def test_history_needs_usable_receipt_evidence(stage_history, report, defect):
    # Intact bytes alone do not bless a held record, an empty list proves no
    # saved bytes, and a miskeyed mapping is not valid landed stage history.
    region, _, path, _, saved, _ = stage_history
    doc = receipts.read_receipt(path)
    assert doc is not None
    row = doc['generation_history'][saved]
    if defect == 'held':
        row['status'] = 'held'
    elif defect == 'no-output-identities':
        row['outputs'] = []
    else:
        doc['generation_history']['f' * 64] = doc['generation_history'].pop(saved)
    receipts.write_json_atomic(path, doc)

    if defect == 'wrong-generation-key':
        captured = report(region, error=True)
        assert not captured.out
        assert 'generation history malformed' in captured.err
    else:
        assert report(region)['reusable_history'] == []
