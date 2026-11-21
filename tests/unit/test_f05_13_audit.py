"""F05-13: the unmanaged worker commits observation.json once, after diagnostics.

Contract protected: the canonical observation is the only observation.json the
unmanaged worker writes, written after plan, diagnostics and policy fields are
final, and every downstream reference (result, finalized proof, completion
envelope) names that file's bytes. Believable bug: the producer or worker writes
a provisional observation.json early (and rewrites it twice), so an interrupted
run leaves a committed-looking file and references can name replaced bytes.

Only the raster/GIS and authority stages are stubbed (the non-GIS CI job has no
numpy/rasterio); the worker's own write, reference and envelope logic is real.
"""
import contextlib
import hashlib
import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest

# worker imports authenticated_v1.supplement, which needs numpy at import time, so the
# no-GIS lane cannot even collect this module; the survey-science lane runs it.
# find_spec only locates numpy; it never imports it.
if importlib.util.find_spec("numpy") is None:
    pytest.skip("worker imports numpy via authenticated_v1.supplement; no-GIS lane lacks it",
                allow_module_level=True)

from skippercast.coastal.authenticated_v1 import worker  # noqa: E402

SHA = "a" * 64


class Authority:
    def close(self):
        pass

    def check(self, *args):
        pass


class Receipt:
    def payload(self):
        return {"capability_closed": True}


@pytest.fixture
def unmanaged(tmp_path, monkeypatch):
    """A healthy unmanaged acquire run; returns (run, writes, out, root)."""
    root = tmp_path
    writes = []
    real_write = worker.write
    job = dict(execution_contract="coastal-authenticated-job-v1", stage="acquire", source_domain_grant={},
               root=str(root), job_id="J", lease_token="L", source_root=str(root), source_relative_path="s.bag",
               code_sha="c" * 64, deps_sha="d" * 64, params_sha="p" * 64, input_manifest_sha="i" * 64,
               segment_id="seg")
    packet = dict(source=dict(path="s.bag", sha256=SHA, bytes=1, contract="coastal-native-source-v1"),
                  metadata_sha256="m" * 64, synthetic=True, source_row={}, vertical=None, fixed_center_plan={},
                  segment_id="seg", segment={}, rights={}, policy_sha256="p" * 64, trial_policy_sha256="t" * 64,
                  trial_policy_evidence={"sha256": "t" * 64})

    def spy_write(path, document):
        writes.append(Path(path).name)
        return real_write(path, document)

    def produce_snapshot(view, root_, source, *, output_dir, collector, write_observation, **kwargs):
        collector(dict(depth=None))
        payload = dict(schema="coastal-authenticated-observation-v1", machine_holds=[], facts_digest="f" * 64,
                       native_facts={}, valid_support=dict(path="mask.tif", sha256="b" * 64, bytes=1, contract="coastal-native-support-v2"))
        if write_observation:  # the producer's own provisional write, as in observer.produce_snapshot
            worker.write(Path(root_) / output_dir / "observation.json", payload)
        return payload

    @contextlib.contextmanager
    def authenticate(*args, **kwargs):
        yield types.SimpleNamespace(finalize=Receipt)

    for name, value in dict(
            read_job=lambda path: dict(job), runtime_limits=lambda: {"caps": 1}, validate_clock=lambda j: float("inf"),
            bind_reserved_source=lambda *a: (dict(packet), Authority()), authenticate=authenticate,
            limit_artifact_file_size=lambda: 1, profile=lambda name, p: dict(name="", pairs=256, side=16),
            policy_sha=lambda name, p: "p" * 64, read_header=lambda *a: dict(vertical={}),
            plan_header=lambda header, spec: dict(window=[0, 0, 16, 16]), produce_snapshot=produce_snapshot,
            summarize=lambda captured, digest: dict(diagnostics_digest="d" * 64),
            evaluate=lambda *a, **k: dict(holds=[], paired_eligibility_quality_pass=True),
            libraries=dict, implementation=dict, write=spy_write).items():
        monkeypatch.setattr(worker, name, value)
    monkeypatch.setitem(sys.modules, "numpy", types.SimpleNamespace(
        savez_compressed=lambda path, **arrays: Path(path).write_bytes(b"npz")))
    out = root / "var/coastal/jobs/J/L/output"
    return (lambda: worker.run(root / "job.json", out)), writes, out, root


def test_healthy_unmanaged_run_writes_observation_once_after_diagnostics(unmanaged, capsys):
    run, writes, out, root = unmanaged
    assert run() == 0
    assert writes.count("observation.json") == 1
    assert writes.index("diagnostics.json") < writes.index("observation.json")
    final = json.loads((out / "observation.json").read_text())
    assert final["diagnostics"]["path"].endswith("diagnostics.json") and final["plan"]["path"].endswith("plan.json")
    assert final["policy_ready"] is True and final["accepted"] is False and final["commit_required"] is True


def test_every_downstream_reference_names_the_final_observation_bytes(unmanaged, capsys):
    run, writes, out, root = unmanaged
    run()
    sha = hashlib.sha256((out / "observation.json").read_bytes()).hexdigest()
    result = json.loads((out / "result.json").read_text())
    proof = json.loads((out / "finalized-authentication.json").read_text())
    envelope = json.loads(capsys.readouterr().out)
    observation_refs = [a for a in result["artifacts"] if a["contract"] == "coastal-authenticated-observation-v1"]
    assert [a["sha256"] for a in observation_refs] == [sha] and result["observation"]["sha256"] == sha
    assert proof["observation_sha256"] == envelope["observation_sha256"] == sha
    assert envelope["artifacts_digest"] == worker.digest(result["artifacts"])


def test_interrupted_run_leaves_no_committed_looking_observation(unmanaged, monkeypatch):
    run, writes, out, root = unmanaged

    def interrupted(captured, digest):
        raise ValueError("synthetic interruption before diagnostics")

    monkeypatch.setattr(worker, "summarize", interrupted)
    with pytest.raises(ValueError, match="synthetic interruption"):
        run()
    assert (out / "plan.json").exists()  # partial evidence stays inspectable
    assert not (out / "observation.json").exists() and not (out / "result.json").exists()
    assert "observation.json" not in writes
