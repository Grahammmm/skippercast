"""Exercise offline receipt checks with and without Python assertions."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

from tests._support import ROOT


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))
    return hashlib.sha256(path.read_bytes()).hexdigest()


def m2_fixture(root):
    receipts = root / 'local'
    holds = ['native_support_empty', 'vertical_sign_unobserved', 'vertical_units_unobserved']
    plan = write_json(receipts / 'bounded-bridge-plan.json', {'fixture': 'plan'})
    catalog = write_json(receipts / 'queue/catalog.json', {'fixture': 'catalog'})
    result = write_json(receipts / 'queue/result.json', dict(state='held', holds=holds))
    write_json(receipts / 'bounded-controller-execution.json', dict(stdout=json.dumps([
        dict(result=dict(path='result.json', sha256=result)),
    ])))
    write_json(receipts / 'bounded-queue-readback.json', dict(jobs=[
        dict(attempts=n, stage='acquire', state='held') for n in (0, 1)
    ]))
    summary = dict(
        task_id='t_6fe43227', acquire_state='held', holds=holds, within_caps=True,
        native_valid_cells=0, network_requests=1, transferred_bytes=313215664,
        window=[6656, 0, 512, 512], next_tile_index=1, review_required=True,
        reservation_recovery=dict(original_attempts=0, new_job_wall_seconds=240,
                                  regional_caps_raised=False, budget_reset=False),
        declared_deep_datum=dict(datum_class='unstated', uncertainty_status='datum_offset_unbounded',
                                 navigation='not-for-navigation', uncertainty_bound_required=False),
        qualify_valid_pixel_counts_per_band=None, deepest_mapped_cell=None,
        product_uncertainty_histogram=None, native_valid_support_map_mask_sha256=None,
        map_handoff_hashes=None, semantic_accepted=False, mapping_accepted=False,
        publication_accepted=False, next_tile_authorized=False,
        plan_sha256=plan, catalog_sha256=catalog, result_sha256=result,
    )
    write_json(root / 'research/receipts/coast-c1-m2-held.json', summary)
    receipt_sha = write_json(receipts / 'receipt.json', summary)
    write_json(receipts / 'output-hashes.json', {'receipt.json': receipt_sha})
    return receipts


@pytest.mark.parametrize('args', [(), ('-O',)])
def test_complete_m2_fixture_cannot_pass_with_wrong_hash(tmp_path, args):
    receipts = m2_fixture(tmp_path)
    command = [sys.executable, '-B', *args, '-m', 'tests.unit.test_f30_11_audit', 'm2', str(tmp_path)]
    good = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=30)
    # Change only the hash expectation; all checked files are still present and readable.
    write_json(receipts / 'output-hashes.json', {'receipt.json': '0' * 64})
    bad = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=30)
    if args:
        assert good.returncode != 0 and 'Evidence checks require Python assertions' in good.stderr
        assert 'PASS' not in good.stdout
        assert 'Evidence checks require Python assertions' in bad.stderr
    else:
        assert good.returncode == 0 and 'PASS' in good.stdout, good.stderr
        assert 'AssertionError: receipt.json' in bad.stderr
    assert bad.returncode != 0 and 'PASS' not in bad.stdout


@pytest.mark.parametrize('checker', [
    'research.scripts.check_coast_c1_discovery',
    pytest.param('research.scripts.coast_mvp.verify_c4_real', marks=pytest.mark.gis),
])
def test_optimized_cli_refuses_before_reading_evidence(tmp_path, checker):
    missing = str(tmp_path / 'not-present')
    out = tmp_path / 'output.json'
    options = (['--packet', missing, '--manifest', missing, '--output', str(out)]
               if checker.endswith('verify_c4_real') else ['--receipts', missing])
    result = subprocess.run([sys.executable, '-B', '-O', '-m', checker, *options], cwd=ROOT,
                            capture_output=True, text=True, timeout=30)
    assert result.returncode != 0
    assert 'Evidence checks require Python assertions' in result.stderr
    assert 'PASS' not in result.stdout and not out.exists()


if __name__ == '__main__':
    from research.scripts import check_coast_c1_m2 as m2

    m2.ROOT = Path(sys.argv[2])
    print(json.dumps(m2.verify(m2.ROOT / 'local')))
