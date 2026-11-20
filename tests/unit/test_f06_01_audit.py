"""F06-01: agreement without byte identity must not authorize receipt repair."""
import json

import pytest

from skippercast.coastal import prefetch as p
from tests.unit.test_coast_prefetch import Server, isolated_retry_state, row, runner  # noqa: F401


@pytest.fixture
def receipts(tmp_path):
    server = Server()
    run = runner(tmp_path, server)
    planned = row()
    directory = run.root / planned['source']
    directory.mkdir(parents=True)
    run.mirror.mkdir()
    record = {key: planned[key] for key in ('url', 'bytes', 'sha256', 'licence', 'segments')}
    record.update(final_url=planned['url'], path=str(directory / p.filename(planned)),
                  verification='publisher-sha256')
    return run, server, record, directory / 'manifest.jsonl', run.mirror / (planned['source'] + '.jsonl')


@pytest.mark.parametrize('case', ['missing-digest', 'malformed-digest', 'missing-size', 'equal-float-size',
                                  'duplicate-digest-key'])
def test_ambiguous_byte_identity_preserves_both_receipts(receipts, case):
    # Tuple equality is not evidence: absent/malformed values match, floats compare equal to ints,
    # and a JSON decoder using last-wins can hide the first of two contradictory hashes.
    run, server, record, primary, mirror = receipts
    other = dict(record, licence='stale')
    if case == 'missing-digest':
        del record['sha256'], other['sha256']
    elif case == 'malformed-digest':
        record['sha256'] = other['sha256'] = 'unknown'
    elif case == 'missing-size':
        del record['bytes'], other['bytes']
    elif case == 'equal-float-size':
        record['bytes'] = float(record['bytes'])
    primary.write_text(json.dumps(record) + '\n')
    mirror_text = json.dumps(other)
    if case == 'duplicate-digest-key':
        mirror_text = '{"sha256": "' + '0' * 64 + '", ' + mirror_text[1:]
    mirror.write_text(mirror_text + '\n')
    before = primary.read_bytes(), mirror.read_bytes()

    with pytest.raises(p.Hold, match='preserve'):
        run.run()

    assert (primary.read_bytes(), mirror.read_bytes()) == before
    assert json.loads(run.status.read_text())['state'] == 'stopped'
    assert not server.calls


def test_manifest_repairs_missing_copy(receipts):
    # A valid primary can recreate a missing mirror; the guard must not require two copies.
    run, server, record, primary, mirror = receipts
    primary.write_text(json.dumps(record, sort_keys=True) + '\n')
    before = primary.read_bytes()
    run.manifest(row()['source'])
    assert primary.read_bytes() == mirror.read_bytes() == before
    assert not server.calls
