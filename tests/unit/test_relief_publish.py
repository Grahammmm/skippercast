"""Offline R9 acceptance using the actual package and approval chain."""
import hashlib
import io
import json
import os

import pytest

from skippercast.relief import package, publish
from tests.unit import test_relief_package as release_tests
from tests.unit.test_relief_package import assembly, write_json


def sha(data):
    return hashlib.sha256(data).hexdigest()


class MemoryR2:
    def __init__(self):
        self.objects = {}
        self.puts = []
        self.gets = []

    def exists(self, key):
        return key in self.objects

    def put(self, key, chunks):
        self.puts.append(key)
        body = b''.join(chunks)  # only commit if the checked producer reaches EOF
        if key in self.objects:
            raise FileExistsError(key)
        self.objects[key] = body

    def get(self, key):
        self.gets.append(key)
        return io.BytesIO(self.objects[key])


@pytest.fixture
def approved(tmp_path, assembly, monkeypatch):
    chunk = json.dumps([[128, 64, sha(b'synthetic tile')]]).encode()
    monkeypatch.setattr(release_tests, 'LAYERS', release_tests.LAYERS | {
        release_tests.CHUNK: chunk,
        package.DIGEST_ROOT: json.dumps({'chunks': {'8/2_1.json': sha(chunk)}}).encode(),
    })
    region, release, qa, review, approval = release_tests.approved(tmp_path / 'build')
    scope = tmp_path / 'RELIEF-PUBLISH-SCOPE'
    scope.write_text('ALL\n', encoding='utf-8')
    return region.dir, release, qa, review, approval, scope


def make_plan(approved):
    _, release, _, review, approval, scope = approved
    return publish.plan(release.parent, approval, review, scope_path=scope)


def test_full_publish_and_noop_retry(approved):
    # Pins browser-facing keys, and catches trusting existence or rewriting on retries.
    region, _, _, review, _, scope = approved
    scope.write_text(f'{region.name}\n', encoding='utf-8')
    root = (region / package.DIGEST_ROOT).read_bytes()
    archive = (region / package.ARCHIVE).read_bytes()
    chunk = (region / release_tests.CHUNK).read_bytes()
    stem = f'tiles/relief/{region.name}/{sha(archive)}'
    index = f'{stem}.digests/{sha(root)}'
    expected = {f'{stem}.pmtiles': archive, f'{index}/root.json': root, f'{index}/8/2_1.json': chunk}
    store = MemoryR2()
    planned = make_plan(approved)
    assert {obj.key for obj in planned.objects} == expected.keys()
    assert not review.with_name('upload.json').exists()
    receipt = publish.publish(planned, store)
    assert store.objects == expected
    assert store.gets == list(expected) == store.puts
    assert receipt == {
        'schema': 'sc-relief-upload/1',
        'envelope_sha256': sha(review.read_bytes()),
        'objects': [{'key': key, 'sha256': sha(data), 'bytes': len(data)} for key, data in expected.items()],
    }
    receipt_path = review.with_name('upload.json')
    assert json.loads(receipt_path.read_bytes()) == receipt
    os.utime(receipt_path, ns=(1_000_000_000, 1_000_000_000))
    store.gets.clear()
    assert publish.publish(make_plan(approved), store) == receipt
    assert store.gets == list(expected) == store.puts
    assert receipt_path.stat().st_mtime_ns == 1_000_000_000


@pytest.mark.parametrize(('changed', 'error'), [
    ('archive', 'layer hash or size changed'),
    ('chunk', 'layer hash or size changed'),
    ('qa', 'qa.json does not match envelope'),
    ('release', 'release.json does not match envelope'),
])
def test_refuses_post_approval_edits(approved, changed, error):
    # R9 calls verify_chain, even for QA and release files that it doesn't upload.
    region, release, qa, _, _, _ = approved
    path = {'archive': region / package.ARCHIVE, 'chunk': region / release_tests.CHUNK,
            'release': release, 'qa': qa}[changed]
    raw = path.read_bytes()
    path.write_bytes(raw[:-1] + bytes([raw[-1] ^ 1]))
    with pytest.raises(package.ReleaseError, match=error):
        make_plan(approved)


@pytest.mark.parametrize('scope_value', ['unrelated-region\n', None])
def test_refuses_scope_at_publish_even_after_planning(approved, scope_value):
    # A plan can outlive the scope flag. No transport calls may follow revocation.
    scope = approved[-1]
    planned = make_plan(approved)
    if scope_value is None:
        scope.unlink()
    else:
        scope.write_text(scope_value, encoding='utf-8')
    store = MemoryR2()
    with pytest.raises(package.ReleaseError, match='RELIEF-PUBLISH-SCOPE'):
        make_plan(approved)
    with pytest.raises(package.ReleaseError, match='RELIEF-PUBLISH-SCOPE'):
        publish.publish(planned, store)
    assert not store.puts and not store.gets and not planned.receipt_path.exists()


@pytest.mark.parametrize('current_display', ['private', 'excluded'])
def test_refuses_source_now_held_by_registry(approved, assembly, current_display):
    # A release's frozen public claim cannot override the current decision.
    catalog = assembly / 'catalog/sources.json'
    doc = json.loads(catalog.read_bytes())
    doc['sources'][0]['rights']['public_display'] = current_display
    write_json(catalog, doc)
    with pytest.raises(package.ReleaseError, match='does not have public display rights'):
        make_plan(approved)


def test_receipt_cannot_replace_approval(approved):
    # A caller-selected approval filename must not be destroyed by the receipt writer.
    _, release, _, review, approval, scope = approved
    collision = review.with_name('upload.json')
    collision.write_bytes(approval.read_bytes())
    planned = publish.plan(release.parent, collision, review, scope_path=scope)
    store = MemoryR2()
    with pytest.raises(package.ReleaseError, match='overwrite a gate input'):
        publish.publish(planned, store)
    assert not store.puts and collision.read_bytes() == approval.read_bytes()


@pytest.mark.parametrize('defect', ['missing-root', 'unlisted-chunk', 'wrong-chunk-hash'])
def test_refuses_approved_but_incomplete_digest_index(approved, defect):
    # Exercise the inventory gate, not an unrelated stale-approval failure.
    region, release, qa, review, approval, _ = approved
    release_doc = json.loads(release.read_bytes())
    if defect == 'missing-root':
        release_doc['digest_root_sha256'] = None
        release_doc['layers'] = [row for row in release_doc['layers'] if row['path'] != package.DIGEST_ROOT]
        error = 'digest root'
    else:
        root = region / package.DIGEST_ROOT
        chunks = json.loads(root.read_bytes())['chunks']
        if defect == 'unlisted-chunk':
            chunks['8/3_1.json'] = chunks['8/2_1.json']
        else:
            chunks['8/2_1.json'] = '0' * 64
        write_json(root, {'chunks': chunks})
        for row in release_doc['layers']:
            if row['path'] == package.DIGEST_ROOT:
                row.update(sha256=sha(root.read_bytes()), bytes=root.stat().st_size)
                release_doc['digest_root_sha256'] = row['sha256']
        error = 'digest chunk does not match an approved layer'
    write_json(release, release_doc)
    release_sha = sha(release.read_bytes())
    write_json(qa, {'status': 'PASS', 'release_sha256': release_sha})
    envelope = json.loads(review.read_bytes())
    envelope['release']['sha256'] = release_sha
    envelope['qa']['sha256'] = sha(qa.read_bytes())
    envelope['layers'] = release_doc['layers']
    write_json(review, envelope)
    envelope_sha = sha(review.read_bytes())
    write_json(approval, {'envelope_sha256': envelope_sha,
                          'verdict': f'APPROVED release {region.name} envelope={envelope_sha}'})
    with pytest.raises(package.ReleaseError, match=error):
        make_plan(approved)


def test_bytes_changed_between_check_and_send_abort_without_commit(approved):
    # Mutate after the final preflight, while the sender is checking the remote key.
    region = approved[0]
    planned = make_plan(approved)
    archive = region / package.ARCHIVE
    altered = archive.read_bytes().replace(b'archive', b'changed')

    class RacingR2(MemoryR2):
        def exists(self, key):
            archive.write_bytes(altered)
            return super().exists(key)

    store = RacingR2()
    with pytest.raises(package.ReleaseError, match='send-time hash'):
        publish.publish(planned, store)
    assert store.puts == [planned.objects[0].key]  # the bad bytes reached the send gate
    assert not store.objects and not store.gets and not planned.receipt_path.exists()


@pytest.mark.parametrize('already_present', [False, True])
def test_full_get_refuses_same_size_altered_body(approved, already_present):
    # Corrupt only the end of the response; presence, header prefix and size still agree.
    planned = make_plan(approved)
    obj = planned.objects[0]

    class CorruptReadR2(MemoryR2):
        def get(self, key):
            with super().get(key) as stream:
                raw = stream.read()
            return io.BytesIO(raw[:-1] + bytes([raw[-1] ^ 1]))

    store = CorruptReadR2()
    if already_present:
        store.objects[obj.key] = (planned.region_dir / obj.path).read_bytes()
    with pytest.raises(package.ReleaseError, match='full GET read-back hash or size mismatch'):
        publish.publish(planned, store)
    assert store.gets == [obj.key]
    assert store.puts == ([] if already_present else [obj.key])
    assert not planned.receipt_path.exists()
