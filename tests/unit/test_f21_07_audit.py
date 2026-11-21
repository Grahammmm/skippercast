"""F21-07: a successful session is not proof that its whole batch is complete."""
import json
from pathlib import Path
import re

import pytest

from tests.unit.test_fleet_run_osint import Harness, profile_template


def output_path(doc, vessel_id):
    return Path(doc["output_dir"]) / f"{vessel_id}.json"


def write_profile(doc, vessel_id, **changes):
    profile = dict(profile_template(), **{key: doc[key] for key in ("region", "run_id", "batch_id")},
                   vessel_id=vessel_id)
    profile.update(changes)
    output_path(doc, vessel_id).write_text(json.dumps(profile))


@pytest.mark.parametrize("incomplete", ["absent", "invalid", "wrong-vessel", "old-done"])
def test_resume_targets_only_unvalidated_vessels(tmp_path, incomplete):
    # Regressions: counting an exit-zero result or an unvalidated file as done,
    # skipping a legacy done record with missing output, or redoing completed work.
    h = Harness(tmp_path, boats=3, batch_size=2)
    first, second = h.docs
    good, missing = [boat["vessel_id"] for boat in first["boats"]]
    (complete,) = [boat["vessel_id"] for boat in second["boats"]]
    original = (h.run_dir / "manifests/batch-001.json").read_bytes()
    seen = []
    resume = incomplete == "old-done"

    def session(_cmd, prompt, _cwd, _env, out, _err, _timeout, *, live):
        match = re.search(r"batch manifest (\S+\.json)", prompt)
        assert match is not None
        path = Path(match[1])
        doc = json.loads(path.read_text())
        ids = [boat["vessel_id"] for boat in doc["boats"]]
        seen.append(ids)
        for vessel_id in ids:
            if resume or vessel_id != missing:
                write_profile(doc, vessel_id, notes="Resumed profile" if resume else "Original profile")
            elif incomplete == "invalid":
                write_profile(doc, vessel_id, schema_version="0.0.0")
            elif incomplete == "wrong-vessel":
                output_path(doc, vessel_id).write_bytes(output_path(doc, good).read_bytes())
        out.write_text('{"subtype":"success"}')
        return 0, False

    if resume:
        for doc, vessel_id in ((first, good), (second, complete)):
            write_profile(doc, vessel_id)
        state = h.state()
        state["osint"] = {"batches": {
            "batch-001": {"status": "done", "missing": [missing]},
            "batch-002": {"status": "done", "missing": []},
        }}
        (h.run_dir / "state.json").write_text(json.dumps(state))
    else:
        code, counts = h.run(session=session, parallel=1)
        state = h.state()["osint"]["batches"]["batch-001"]
        assert (state["status"], state["profiles"], state["missing"]) == ("partial", 1, [missing])
        assert (code, counts["partial"], counts["done"]) == (1, 1, 1)
        assert seen == [[good, missing], [complete]]
        seen.clear()

    saved = output_path(first, good).read_bytes()
    saved_complete = output_path(second, complete).read_bytes()
    resume = True
    code, counts = h.run(session=session, parallel=1)
    assert (code, counts["done"], counts["skipped_done"]) == (0, 2, 1)
    assert counts["partial"] == 0
    assert seen == [[missing]]
    state = h.state()["osint"]["batches"]["batch-001"]
    assert (state["status"], state["profiles"], state["missing"]) == ("done", 2, [])
    assert output_path(first, good).read_bytes() == saved
    assert output_path(second, complete).read_bytes() == saved_complete
    assert (h.run_dir / "manifests/batch-001.json").read_bytes() == original

    code, counts = h.run(session=session)
    assert (code, counts["skipped_done"]) == (0, 2)
    assert seen == [[missing]], "a complete run must not launch another session"
