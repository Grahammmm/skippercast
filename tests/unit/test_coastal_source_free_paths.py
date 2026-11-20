"""Producer database opens in source_free use the literal path, read-only."""
from contextlib import closing
import json
import sqlite3
from types import SimpleNamespace

import pytest

from skippercast.coastal.coordinator import source_free
from skippercast.coastal.handoff.common import write

NAMES = ["plain", "hash#dir", "query?dir", "pct%23dir", "pct%3Fdir", "sp ace", "uni\u00e9", "a?mode=rw#b%25"]


def _make(path, marker):
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE marker(v TEXT)")
    con.execute("INSERT INTO marker VALUES (?)", (marker,))
    con.commit()
    con.close()


def _marker(con):
    try:
        return con.execute("SELECT v FROM marker").fetchone()[0]
    finally:
        con.close()


def _inventory(root):
    return sorted((str(p.relative_to(root)), p.stat().st_size) for p in root.rglob("*") if p.is_file())


@pytest.mark.parametrize("name", NAMES)
@pytest.mark.parametrize("where", ["parent", "basename"])
def test_literal_reserved_path_selects_requested_database(tmp_path, name, where):
    target = tmp_path / name / "p.sqlite" if where == "parent" else tmp_path / (name + ".sqlite")
    _make(target, "requested")
    before = _inventory(tmp_path)
    assert _marker(source_free._open_producer(target)) == "requested"
    assert _inventory(tmp_path) == before


def test_decoded_or_truncated_decoy_is_not_selected(tmp_path):
    requested = tmp_path / "a%23b?mode=rw.sqlite"
    _make(requested, "requested")
    _make(tmp_path / "a#b?mode=rw.sqlite", "decoded")
    _make(tmp_path / "a%23b", "truncated")
    before = _inventory(tmp_path)
    assert _marker(source_free._open_producer(requested)) == "requested"
    assert _inventory(tmp_path) == before


def test_missing_after_closed_check_never_created(tmp_path, monkeypatch):
    target = tmp_path / "q?x#y.sqlite"
    _make(target, "m")
    real = source_free.require_closed_database

    def check_then_remove(path):
        out = real(path)
        target.unlink()
        return out

    monkeypatch.setattr(source_free, "require_closed_database", check_then_remove)
    with pytest.raises(sqlite3.OperationalError):
        source_free._open_producer(target)
    assert _inventory(tmp_path) == []


def test_closed_sidecars_still_required(tmp_path):
    target = tmp_path / "d.sqlite"
    _make(target, "m")
    (tmp_path / "d.sqlite-journal").write_bytes(b"")
    assert _marker(source_free._open_producer(target)) == "m"
    for suffix in ("-wal", "-journal"):
        sidecar = tmp_path / ("d.sqlite" + suffix)
        sidecar.write_bytes(b"x")
        with pytest.raises(ValueError):
            source_free._open_producer(target)
        sidecar.unlink()
    link = tmp_path / "d.sqlite-wal"
    link.symlink_to(tmp_path / "elsewhere")
    with pytest.raises(ValueError):
        source_free._open_producer(target)


def _make_retained_db(path, identity, result_sha, marker):
    with closing(sqlite3.connect(path)) as db, db:
        db.executescript("""
            CREATE TABLE jobs(job_id, state, stage, result_sha, record_json);
            CREATE TABLE authenticated_artifacts(job_id, path);
            CREATE TABLE segments(segment_id, record_json);
        """)
        record = dict(identity, execution_contract="coastal-authenticated-job-v1", marker=marker)
        db.execute("INSERT INTO jobs VALUES (?, 'done', 'qualify', ?, ?)",
                   (identity["job_id"], result_sha, json.dumps(record)))
        db.execute("INSERT INTO segments VALUES (?, ?)",
                   (identity["segment_id"], json.dumps({"segment_id": "seg", "marker": marker})))


@pytest.mark.parametrize("use_plan_segment", [True, False], ids=["plan-segment", "sqlite-segment"])
def test_import_retained_preserves_database_provenance(tmp_path, monkeypatch, use_plan_segment):
    origin = tmp_path / "origin"
    origin.mkdir()
    requested = origin / "producer?mode=ro.sqlite"
    decoy = origin / "producer"
    identity = dict(job_id="job:1", stage="qualify", segment_id="seg",
                    code_sha="a" * 64, deps_sha="b" * 64, params_sha="c" * 64,
                    input_manifest_sha="d" * 64)
    qualified = {"path": "var/coastal/jobs/job-1/lease/output/result.json", "sha256": "e" * 64}
    # Both databases satisfy the identity checks. A truncated URI can silently
    # import the wrong record at either read site unless we check the payload.
    _make_retained_db(requested, identity, qualified["sha256"], "requested")
    _make_retained_db(decoy, identity, qualified["sha256"], "decoy")
    before = {p.name: p.read_bytes() for p in origin.iterdir()}

    plan: dict[str, object] = dict(sha256="f" * 64, packets=["synthetic-packet"], side=128)
    if use_plan_segment:
        plan["segment"] = {"segment_id": "seg", "marker": "plan"}
    item = dict(packet=dict(qualified_result=qualified, synthetic=True),
                result_ref=qualified, facts=dict(header=dict(window="synthetic-window")))
    result = dict(identity, lease_token="lease", artifacts=[])
    # Supply prepared science inputs, but leave source selection, SQL reads,
    # proof generation and registration in the real import caller.
    monkeypatch.setattr(source_free.contained_batch, "_prepare",
                        lambda *args, **kwargs: ([item], [{"segment_id": "seg"}]))
    monkeypatch.setattr(source_free, "_copy_refs", lambda *args: (result, []))

    segments = []
    with closing(sqlite3.connect(":memory:")) as db:
        db.executescript(source_free.SCHEMA)
        store = SimpleNamespace(root=(tmp_path / "fresh").resolve(), managed_outputs=None,
                                db=db, transaction=lambda: db, write_artifact=lambda path, doc, **kw: write(path, doc),
                                add_segment=segments.append, event=lambda *args: None)
        source_free.import_retained(store, source_root=origin, source_db=requested, plan_ref=plan,
                                    now=100, deadline=200)
        [(record_json,)] = db.execute("SELECT record_json FROM retained_producers").fetchall()
    proof = json.loads(record_json)
    assert proof["original_job"]["marker"] == "requested"
    assert proof["producer_source_db"] == str(requested.resolve())
    assert segments == [{"segment_id": "seg", "marker": "plan" if use_plan_segment else "requested"}]
    assert {p.name: p.read_bytes() for p in origin.iterdir()} == before
