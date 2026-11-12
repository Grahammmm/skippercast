import pytest
pytest.importorskip('numpy')
pytest.importorskip('rasterio')
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from skippercast.coastal import stage_cli
from skippercast.coastal.handoff.common import digest, ref, write
from skippercast.coastal.render import terrain_only
from tests.gis.test_coastal_terrain_dispatch_adoption_guards import accepted, approve  # noqa: F401

NOW = datetime(2026, 10, 9, tzinfo=timezone.utc)
WALL = 60


def make_job(root, document, *, valid_after):
    approve(root, document, valid_until=(NOW + timedelta(seconds=valid_after)).isoformat())
    write(root / 'input.json', document)
    reference = ref(root, root / 'input.json', terrain_only.INPUT)
    params = dict(terrain_root=str(root), terrain_context_digest=terrain_only.context(document))
    return dict(root=str(root), stage='render', job_id='synthetic-job',
                segment=dict(segment_id=document['segment_id'], synthetic=True),
                lease_token='synthetic-token', code_sha='a' * 64, deps_sha='b' * 64,
                params=params, params_sha=digest(params), input_manifest=reference,
                input_manifest_sha=reference['sha256'],
                budget=dict(wall_s=WALL, bytes=1000000, requests=0),
                deadline_utc=(NOW + timedelta(seconds=WALL)).timestamp())


def test_review_short_of_horizon_refused_before_render(accepted):
    root, document, *_ = accepted
    job = make_job(root, document, valid_after=30)
    with patch.object(terrain_only, 'preview', side_effect=AssertionError('rendered')):
        with pytest.raises(ValueError, match='review_insufficient_validity'):
            stage_cli.execute(job, 'out', now=NOW)
    assert not (root / 'out' / 'preview').exists()


def test_strict_equal_expiry_refuses_and_one_second_more_succeeds(accepted):
    root, document, *_ = accepted
    job = make_job(root, document, valid_after=WALL)
    with pytest.raises(ValueError, match='review_insufficient_validity'):
        stage_cli.execute(job, 'out', now=NOW)
    job = make_job(root, document, valid_after=WALL + 1)
    result = stage_cli.execute(job, 'out', now=NOW)
    assert result['state'] == 'done' and result['holds'] == []
    assert len(result['artifacts']) == 2
    assert (root / 'out' / 'preview' / 'complete.json').exists()


def test_same_horizon_reaches_both_verifications(accepted):
    root, document, *_ = accepted
    job = make_job(root, document, valid_after=WALL + 100)
    seen = {}
    real_verify, real_preview = terrain_only.verify, terrain_only.preview

    def verify(*a, **k):
        seen['verify'] = k.get('minimum_valid_until')
        return real_verify(*a, **k)

    def preview(*a, **k):
        seen['preview'] = k.get('minimum_valid_until')
        return real_preview(*a, **k)

    with patch.object(terrain_only, 'verify', verify), patch.object(terrain_only, 'preview', preview):
        stage_cli.execute(job, 'out', now=NOW)
    expected = NOW + timedelta(seconds=WALL)
    assert seen == dict(verify=expected, preview=expected)


def test_delay_between_admission_and_execution_is_rechecked(accepted):
    root, document, *_ = accepted
    job = make_job(root, document, valid_after=90)
    # Initially admissible at NOW, but a later start no longer has enough review.
    terrain_only.verify(root, document, now=NOW, minimum_valid_until=NOW + timedelta(seconds=WALL))
    with pytest.raises(ValueError, match='review_insufficient_validity'):
        stage_cli.execute(job, 'out', now=NOW + timedelta(seconds=40))


def test_cli_reports_failed_terminal_without_artifacts(accepted, tmp_path, capsys):
    root, document, *_ = accepted
    job = make_job(root, document, valid_after=30)
    job['deadline_utc'] = (NOW + timedelta(hours=1)).timestamp()
    job_path = tmp_path / 'job.json'
    job_path.write_text(json.dumps(job))

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW

    with patch.object(stage_cli, 'datetime', Clock):
        code = stage_cli.main(['run', '--job', str(job_path), '--out', str(root / 'out')])
    assert code == 5
    assert 'failed_terminal' in capsys.readouterr().out
    result = json.loads((root / 'out' / 'result.json').read_text())
    assert result['state'] == 'failed_terminal' and result['artifacts'] == []
    assert any('review_insufficient_validity' in h for h in result['holds'])
    assert not (root / 'out' / 'preview').exists()
