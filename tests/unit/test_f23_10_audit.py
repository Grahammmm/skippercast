"""Exercise the workflow's local ZIP/receipt handoff without running Actions."""

import hashlib
import json
import os
import shlex
import sys
from io import BytesIO
from zipfile import ZipFile

import pytest
import yaml

from scripts import verify_legal_review_artifact as verifier
from tests._support import ROOT

WORKFLOW = ROOT / '.github/workflows/regional-legal-review.yml'
JURISDICTION = 'synthetic-coast'


def _python_step(step):
    # Run the checked-in Python body without invoking a shell or the collector.
    _, rest = step['run'].split("python - <<'PY'\n", 1)
    body, tail = rest.split('\nPY\n', 1)
    exec(compile(body, str(WORKFLOW), 'exec'), {})
    return tail


@pytest.mark.parametrize('partial', [False, True], ids=['exact-zip', 'partial-unverified'])
def test_legal_review_transport(tmp_path, monkeypatch, partial):
    # A verifier unit test cannot detect a workflow uploading the wrong files.
    steps = yaml.safe_load(WORKFLOW.read_text())['jobs']['packet']['steps']
    verify_step = next(s for s in steps if s.get('name') == 'Verify archived source identity and bytes')
    summary_step = next(s for s in steps if s.get('name') == 'Report coverage and unresolved sources')
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv('JURISDICTION', JURISDICTION)
    summary = tmp_path / 'summary.md'
    monkeypatch.setenv('GITHUB_STEP_SUMMARY', str(summary))
    source_dir = tmp_path / 'var/rules' / JURISDICTION
    source_dir.mkdir(parents=True)
    source, url = 'synthetic-rules', 'https://example.invalid/rules.pdf'
    pdf = b'%PDF-1.7\nSynthetic fixture bytes only\n'
    registry = {'sources': {source: {'url': url, 'normalization': 'pdf-bytes-v1'}}}
    status = 'error' if partial else 'ok'
    record: dict[str, object] = {'status': status, 'url': url}
    if not partial:
        record['data'] = {'normalization': 'pdf-bytes-v1', 'content_sha256': hashlib.sha256(pdf).hexdigest()}
        (source_dir / f'{source}.pdf').write_bytes(pdf)
    packet = {'jurisdiction_id': JURISDICTION, 'collected_at': '2026-01-01T01:00:00Z',
              'rules_content_sha256': verifier.content_hash(registry), 'sources': {source: record}}
    coverage = {'jurisdiction_id': JURISDICTION, 'rules_review_status': 'review-required' if partial else 'current',
                'checks': {source: {'source_status': status, 'status': 'unavailable' if partial else 'unchanged'}}}
    for name, data in [('packet', packet), ('coverage', coverage)]:
        (source_dir / f'{name}.json').write_text(json.dumps(data), encoding='utf-8')
    for path in source_dir.iterdir():
        os.utime(path, (1767229200, 1767229200))

    command = _python_step(verify_step)
    interpreter, *argv = shlex.split(os.path.expandvars(command.replace('\\\n', '')))
    assert (interpreter, argv[0]) == ('python', 'scripts/verify_legal_review_artifact.py')
    monkeypatch.setattr(sys, 'argv', argv)
    monkeypatch.setattr(verifier, 'jurisdiction_files', lambda _: ({'id': JURISDICTION}, registry, None))
    if partial:
        with pytest.raises(SystemExit) as refused:
            verifier.main()
        assert refused.value.code == 1
    else:
        verifier.main()

    outcome = 'failure' if partial else 'success'
    step_id = verify_step.get('id')
    if 'VERIFICATION_OUTCOME' in summary_step['env']:
        assert summary_step['env']['VERIFICATION_OUTCOME'] == '${{ steps.' + step_id + '.outcome }}'
        monkeypatch.setenv('VERIFICATION_OUTCOME', outcome)
    _python_step(summary_step)

    # Model the local upload selection and transport wrapper, not the hosted action.
    selected = {"always()", f"always() && steps.{step_id}.outcome == '{outcome}'"}
    if partial:
        selected.add(f"always() && steps.{step_id}.outcome != 'success'")
    uploads = [s['with'] for s in steps if s.get('uses', '').startswith('actions/upload-artifact@')
               and s.get('if') in selected]
    upload, = uploads
    paths = [tmp_path / p.replace('${{ matrix.jurisdiction }}', JURISDICTION)
             for p in upload['path'].splitlines()]
    root = paths[0] if len(paths) == 1 and paths[0].is_dir() else paths[0].parent
    wrapper = BytesIO()
    with ZipFile(wrapper, 'w') as zipped:
        for path in paths:
            for leaf in path.iterdir() if path.is_dir() else [path]:
                zipped.write(leaf, leaf.relative_to(root))
    report = summary.read_text()
    with ZipFile(wrapper) as zipped:
        if partial:
            assert sorted(zipped.namelist()) == ['coverage.json', 'packet.json']
            assert 'unverified' in upload['name'] and 'Unverified collection' in report
            assert 'sha256sum' not in report
            print('Partial collection: verifier exit 1; unverified upload and summary; no receipt')
        else:
            inner_name = f'{JURISDICTION}.zip'
            assert sorted(zipped.namelist()) == [inner_name, 'verification.json']
            inner = zipped.read(inner_name)
            assert inner == source_dir.with_suffix('.zip').read_bytes()
            digest = hashlib.sha256(inner).hexdigest()
            assert digest == json.loads(zipped.read('verification.json'))['archive_sha256']
            assert 'unverified' not in upload['name'] and f'sha256sum {inner_name}' in report
            print(f'Exact inner ZIP SHA-256: {digest}')
    assert 'human legal review, not season or access clearance' in report
