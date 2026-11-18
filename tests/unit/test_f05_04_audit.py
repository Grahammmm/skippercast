"""F05-04: restart after an interrupted manifest publish (both result names, link count 2).

Contract: produce() completes idempotently, with zero catalog reads, only when
usable-inputs.json and usable-inputs.pending are the same regular inode, have exactly
those two links, and carry the bytes pinned by result-intent.json. A third link, a
different inode or changed bytes must still hold with every artifact preserved.
Believable bugs: (a) restart refuses a finished result (the original failure);
(b) the relaxed link check accepts any hard link; (c) recovery skips the intent
length/hash pin or re-runs the catalog pass.
"""
import os

import pytest

from skippercast.coastal import cached_inventory as ci

NOW, HORIZON = 1.0, 100.0


@pytest.fixture
def env(tmp_path, monkeypatch):
    out = tmp_path / "out"
    plan = {"output_root": str(out)}
    calls = []
    now, horizon = ci.clock_window(NOW, HORIZON)

    def fake_inventory(root, plan_, *, now, horizon):
        calls.append(1)
        return {"plan_sha256": ci.digest(plan_), "now": now, "prospective_horizon": horizon, "usage": {"metadata_bytes": 0}}

    monkeypatch.setattr(ci, "metadata_reservation", lambda p: 0)
    monkeypatch.setattr(ci, "inventory", fake_inventory)
    first = ci.produce(tmp_path, plan, out, now=NOW, horizon=HORIZON)
    assert first["status"] == "completed" and len(calls) == 1
    calls.clear()
    return out, plan, calls, first


def rerun(env):
    out, plan, _calls, _first = env
    return ci.produce(out.parent, plan, out, now=NOW, horizon=HORIZON)


def snapshot(out):
    return {p.name: (p.stat().st_ino, p.stat().st_nlink, p.read_bytes()) for p in out.iterdir()}


def interrupted(out):
    """State left when the process dies after link(pending, manifest), before pending.unlink()."""
    os.link(out / "usable-inputs.json", out / "usable-inputs.pending")


def test_both_names_same_inode_recover_without_catalog_read(env):
    out, _plan, calls, first = env
    manifest_bytes = (out / "usable-inputs.json").read_bytes()
    interrupted(out)
    assert (out / "usable-inputs.json").stat().st_nlink == 2
    result = rerun(env)
    assert result["status"] == "completed_recovered"
    assert result["manifest_sha256"] == first["manifest_sha256"]
    assert result["catalog_metadata_bytes_this_call"] == 0
    assert calls == []
    assert not (out / "usable-inputs.pending").exists()
    assert (out / "usable-inputs.json").stat().st_nlink == 1
    assert (out / "usable-inputs.json").read_bytes() == manifest_bytes
    # Idempotent: a further restart reuses the finished result, still with no catalog read.
    assert rerun(env)["status"] == "completed_reused" and calls == []


def test_clean_finished_state_still_reuses(env):
    result = rerun(env)
    assert result["status"] == "completed_reused" and env[2] == []


def test_third_link_holds_and_preserves_everything(env):
    out, *_ = env
    interrupted(out)
    os.link(out / "usable-inputs.json", out / "extra-link")
    before = snapshot(out)
    with pytest.raises(ValueError, match="owned regular inventory artifact required"):
        rerun(env)
    assert snapshot(out) == before and env[2] == []


def test_third_link_outside_output_holds(env, tmp_path):
    out, *_ = env
    interrupted(out)
    os.link(out / "usable-inputs.json", tmp_path / "elsewhere")
    before = snapshot(out)
    with pytest.raises(ValueError, match="owned regular inventory artifact required"):
        rerun(env)
    assert snapshot(out) == before and env[2] == []


def test_different_inodes_each_with_a_second_link_hold(env, tmp_path):
    out, *_ = env
    payload = (out / "usable-inputs.json").read_bytes()
    (out / "usable-inputs.pending").write_bytes(payload)
    os.link(out / "usable-inputs.json", tmp_path / "other-a")
    os.link(out / "usable-inputs.pending", tmp_path / "other-b")
    assert (out / "usable-inputs.json").stat().st_ino != (out / "usable-inputs.pending").stat().st_ino
    before = snapshot(out)
    with pytest.raises(ValueError, match="owned regular inventory artifact required"):
        rerun(env)
    assert snapshot(out) == before and env[2] == []


@pytest.mark.parametrize("mutate", ["same_length", "longer"])
def test_changed_bytes_hold_and_preserve_both_names(env, mutate):
    out, *_ = env
    interrupted(out)
    manifest = out / "usable-inputs.json"
    data = manifest.read_bytes()
    manifest.write_bytes(data[:-2] + b"X\n" if mutate == "same_length" else data + b" ")
    before = snapshot(out)
    with pytest.raises(ValueError, match="prepared result differs; preserve and hold"):
        rerun(env)
    assert snapshot(out) == before and env[2] == []


def test_symlinked_pending_is_not_a_linked_pair(env, tmp_path):
    out, *_ = env
    os.symlink(out / "usable-inputs.json", out / "usable-inputs.pending")
    before = {p.name for p in out.iterdir()}
    result = None
    try:
        result = rerun(env)
    except ValueError:
        pass
    # Whatever the pre-existing policy does with a symlink, it must never be treated as recovery.
    assert result is None or result["status"] != "completed_recovered"
    assert {p.name for p in out.iterdir()} == before and env[2] == []
