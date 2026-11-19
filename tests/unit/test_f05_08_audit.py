"""F05-08: an edit to either shared BAG dependency retires queued work."""
import pytest

from tests._coastal_operations import Harness, export_package, policy


@pytest.mark.parametrize('dependency', ['util/units.py', 'platform/bottom_targets.py'])
def test_shared_bag_dependency_change_blocks_stale_dispatch(tmp_path, dependency):
    export = export_package(tmp_path / 'runtime')
    ops = Harness(tmp_path, export, policy_value=policy(lease_s=30))
    try:
        old_identity = (ops.code, ops.deps)
        stale = ops.job('stale', 'done')

        # A same-named file under the artifact root is not executable evidence.
        unrelated = ops.root / 'src' / 'skippercast' / dependency
        unrelated.parent.mkdir(parents=True)
        unrelated.write_text('# artifact, not runtime code\n')
        assert tuple(ops._implementation_identity()) == old_identity

        # Each case changes exactly one source file in the isolated runtime.
        source = export / 'skippercast' / dependency
        source.write_bytes(source.read_bytes() + b'\n# updated runtime build\n')
        new_code, new_deps = ops._implementation_identity()
        outcome = ops.run(max_jobs=1)
        assert outcome == [{'state': 'idle'}], (dependency, old_identity, (new_code, new_deps), outcome)
        assert new_code != old_identity[0]
        assert new_deps == old_identity[1]
        assert ops.jobs()[stale]['state'] == 'stale'
        assert ops.lease(stale) is None and not ops.job_dir(stale).exists()
        assert ops.launches() == []

        # An explicitly enqueued job bound to the current identity still works.
        ops.code, ops.deps = new_code, new_deps
        fresh = ops.job('fresh', 'done')
        [result] = ops.run(max_jobs=1)
        assert (result['state'], result['job_id']) == ('done', fresh)
        assert ops.launches() == ['fresh.1.launch']
    finally:
        ops.close()
