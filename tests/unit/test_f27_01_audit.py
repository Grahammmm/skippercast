"""Offline CLI receipt verification; no survey data or provider calls."""
import json
import re
import sys

import pytest

from research.scripts import audit_csumb_source_policy as policy
from research.scripts import audit_csumb_vdatum_bridge as bridge


def _receipt_cli(name, tmp_path, monkeypatch):
    empty = tmp_path / 'input.json'
    empty.write_text('{}')

    if name == 'vdatum':
        report = {'checked_at': 'fresh', 'samples': [], 'depth_qualified': False}
        monkeypatch.setattr(bridge, 'compile_review', lambda *_: report)
        return (bridge.main, ['--scc-review', empty, '--bss-review', empty], report,
                'checked_at', 'depth_qualified', True, SystemExit, 'VDatum or source identity changed')

    if name == 'source-policy':
        report = {'checked_at': 'fresh', 'website_redistribution_cleared': False}
        monkeypatch.setattr(policy, 'fetch', lambda _: b'synthetic')
        monkeypatch.setattr(policy, 'audit', lambda *_: report)
        return (policy.main, [], report, 'checked_at', 'website_redistribution_cleared', True,
                ValueError, 'Official CSUMB source-policy pages changed')

    # Only the overlap CLI imports GIS packages; the test does not run GIS work.
    from research.scripts import audit_h11730_cdfw_substrate_overlap as overlap

    cruises = tmp_path / 'cruises.json'
    cruises.write_text('{"archives": {}}')
    for cruise in overlap.CRUISES:
        (tmp_path / f'{cruise}_video_observations.zip').write_bytes(b'synthetic')
    report = {'camera_archive_sha256': {}, 'camera_windows_deduplicated': 1, 'transects': [],
              'cdfw_tile_sha256': [], 'cdfw_class_counts': {'predicted_hard': 1},
              'nearest_existing_usgs_hard_context_m_range': [10, 20]}
    monkeypatch.setattr(overlap, 'review', lambda *_: dict(report))
    args = ['--pairs', empty, '--cruises', cruises, '--camera-cache', tmp_path,
            '--tile-audit', empty, '--tile-cache', tmp_path, '--usgs-context', empty]
    return (overlap.main, args, report, 'reviewed_at', 'cdfw_class_counts', {'predicted_soft': 1},
            ValueError, 'Point Arena camera/substrate evidence changed')


@pytest.mark.parametrize('name', ['vdatum', 'source-policy', pytest.param('overlap', marks=pytest.mark.gis)])
@pytest.mark.parametrize('same_path', [True, False], ids=['same-path', 'distinct-path'])
@pytest.mark.parametrize('changed', [True, False], ids=['changed', 'matching'])
def test_reviewed_receipt_before_output(name, same_path, changed, tmp_path, monkeypatch):
    # Writing first hides a mismatch for the same path and clobbers distinct output.
    main, args, report, timestamp, stable_field, different_value, error, message = _receipt_cli(
        name, tmp_path, monkeypatch)
    baseline = tmp_path / 'reviewed.json'
    output = baseline if same_path else tmp_path / 'new.json'
    prior = {**report, timestamp: 'reviewed'}
    if changed:
        prior[stable_field] = different_value
    reviewed_bytes = (json.dumps(prior) + '\n').encode()
    baseline.write_bytes(reviewed_bytes)
    output_bytes = reviewed_bytes if same_path else b'{"previous": true}\n'
    if not same_path:
        output.write_bytes(output_bytes)
    monkeypatch.setattr(sys, 'argv', [name, *map(str, args), '--verify', str(baseline), '--output', str(output)])

    if changed:
        with pytest.raises(error, match=re.escape(message)):
            main()
        assert output.read_bytes() == output_bytes
        assert baseline.read_bytes() == reviewed_bytes
    else:
        # An open reader still sees the old bytes after an atomic replacement.
        with output.open('rb') as reader:
            main()
            assert reader.read() == output_bytes
        actual = json.loads(output.read_bytes())
        assert actual.pop(timestamp) != 'reviewed'
        assert actual == {k: v for k, v in report.items() if k != timestamp}
        if not same_path:
            assert baseline.read_bytes() == reviewed_bytes
