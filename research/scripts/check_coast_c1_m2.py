"""Offline checks for the dated, held Cal DIG tile-zero pilot; never replay stages."""
import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def sha(path):
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(chunk)
    return result.hexdigest()


def verify(receipts=None):
    summary = json.loads((ROOT / 'research/receipts/coast-c1-m2-held.json').read_text())
    assert summary['task_id'] == 't_6fe43227'
    assert summary['acquire_state'] == 'held'
    assert summary['holds'] == ['native_support_empty', 'vertical_sign_unobserved', 'vertical_units_unobserved']
    assert summary['within_caps'] is True and summary['native_valid_cells'] == 0
    assert summary['network_requests'] == 1 and summary['transferred_bytes'] == 313215664
    assert summary['window'] == [6656, 0, 512, 512] and summary['next_tile_index'] == 1
    assert summary['reservation_recovery']['original_attempts'] == 0
    assert summary['reservation_recovery']['new_job_wall_seconds'] == 240
    assert summary['reservation_recovery']['regional_caps_raised'] is False
    assert summary['reservation_recovery']['budget_reset'] is False
    for field in ('qualify_valid_pixel_counts_per_band', 'deepest_mapped_cell',
                  'product_uncertainty_histogram', 'native_valid_support_map_mask_sha256', 'map_handoff_hashes'):
        assert summary[field] is None, field
    for field in ('semantic_accepted', 'mapping_accepted', 'publication_accepted', 'next_tile_authorized'):
        assert summary[field] is False, field
    assert summary['review_required'] is True
    deep = summary['declared_deep_datum']
    assert deep['datum_class'] == 'unstated' and deep['uncertainty_status'] == 'datum_offset_unbounded'
    assert deep['navigation'] == 'not-for-navigation' and deep['uncertainty_bound_required'] is False
    checked = 0
    if receipts is not None:
        receipts = receipts.resolve(strict=True)
        hashes = json.loads((receipts / 'output-hashes.json').read_text())
        for name, expected in hashes.items():
            path = (receipts / name).resolve(strict=True)
            assert path.is_relative_to(receipts), name
            assert sha(path) == expected, name
            checked += 1
        assert json.loads((receipts / 'receipt.json').read_text()) == summary
        assert sha(receipts / 'bounded-bridge-plan.json') == summary['plan_sha256']
        assert sha(receipts / 'queue/catalog.json') == summary['catalog_sha256']
        execution = json.loads((receipts / 'bounded-controller-execution.json').read_text())
        result_ref = json.loads(execution['stdout'])[0]['result']
        result_path = (receipts / 'queue' / result_ref['path']).resolve(strict=True)
        assert result_path.is_relative_to(receipts / 'queue')
        assert sha(result_path) == summary['result_sha256'] == result_ref['sha256']
        result = json.loads(result_path.read_text())
        assert result['state'] == 'held' and result['holds'] == summary['holds']
        rows = json.loads((receipts / 'bounded-queue-readback.json').read_text())['jobs']
        assert len(rows) == 2 and [r['attempts'] for r in rows] == [0, 1]
        assert all(r['stage'] == 'acquire' and r['state'] == 'held' for r in rows)
    return {'summary': 'PASS: genuine acquire HOLD; absent downstream outputs remain null', 'file_hashes_checked': checked}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--receipts', type=Path)
    args = parser.parse_args()
    print(json.dumps(verify(args.receipts), sort_keys=True))
