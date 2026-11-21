"""A hash-matching PASS is not sufficient when QA recorded failures."""
import json

import pytest

from skippercast.relief import envelope, package, receipts
from tests.unit.test_relief_package import assembly, inputs, run, run_package, sha, write_json


@pytest.fixture(params=[{'failures': ['synthetic QA failure']}, {'failures': []}, {}],
                ids=['listed-failure', 'empty-list', 'omitted'])
def release_with_qa(request, tmp_path, assembly):
    region, manifest = inputs(tmp_path / 'out')
    assert run_package(region, manifest) == 0
    packaged = receipts.check(region, 'package')
    assert packaged.done and packaged.receipt is not None
    gen = packaged.receipt['generation']
    release = region.dir / 'release' / gen / 'release.json'
    report = {'status': 'PASS', 'release_sha256': sha(release)} | request.param
    assert receipts.run_stage(receipts.StageRun(
        region, 'qa', lambda out: write_json(out / 'qa.json', report), 'b' * 64,
        upstream=[receipts.Ref('package')], target=f'qa/{gen}',
    )).state == 'ok'
    return region, gen, release, bool(report.get('failures'))


def test_envelope_creation_checks_qa_failures(release_with_qa, capsys):
    region, gen, _, has_failures = release_with_qa
    review = region.dir / 'review' / gen / 'envelope.json'
    result = run(region, 'envelope', '--generation', gen)
    if has_failures:
        assert result == 1
        assert 'QA PASS report lists failures' in capsys.readouterr().out
        assert not review.exists()
    else:
        assert result == 0
        assert review.is_file()


def test_chain_verification_checks_qa_failures(release_with_qa):
    region, gen, release, has_failures = release_with_qa
    qa = region.dir / 'qa' / gen / 'qa.json'
    review = region.dir / 'review' / gen / 'envelope.json'
    approval = review.with_name('approval.json')
    # Seal even the contradictory report so byte checks cannot mask a missing QA check.
    write_json(review, {
        'schema': envelope.ENVELOPE_SCHEMA, 'region': region.id, 'generation': gen,
        'release': {'path': release.relative_to(region.dir).as_posix(), 'sha256': sha(release)},
        'qa': {'path': qa.relative_to(region.dir).as_posix(), 'sha256': sha(qa)},
        'layers': json.loads(release.read_bytes())['layers'],
    })
    digest = sha(review)
    write_json(approval, {'envelope_sha256': digest,
                          'verdict': f'APPROVED release {region.id} envelope={digest}'})
    if has_failures:
        with pytest.raises(package.ReleaseError, match='QA PASS report lists failures'):
            envelope.verify_chain(approval, review)
    else:
        assert envelope.verify_chain(approval, review).release_sha256 == sha(release)
