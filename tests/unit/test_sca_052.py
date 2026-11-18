"""Synthetic controls for atomic fleet run/enrichment evidence."""
import errno
import json
import os
import stat
from types import SimpleNamespace
from typing import cast

import pytest

from skippercast.fleet import enrich
from skippercast.fleet.adapters import RunContext
from skippercast.fleet.runs import Run


ROWS = [{"z": "café", "a": 2}, {"z": "second", "a": 1}]
BEFORE = b'{"prior": true}\n'


@pytest.fixture(params=["run", "facts", "imported", "report"])
def evidence(request, tmp_path):
    run = Run("SYN", var=tmp_path)
    kind = request.param
    if kind == "run":
        return kind, run.dir / "rows.jsonl", lambda rows: run.write_jsonl("rows.jsonl", iter(rows))

    adapter_id = "operator-site" if kind == "facts" else "file-import"
    binding = SimpleNamespace(id="synthetic", adapter=adapter_id)
    region = SimpleNamespace(sources=[binding], enabled_sources=lambda: [binding], binding=lambda _: binding)
    ctx = cast(RunContext, SimpleNamespace(run_dir=run.dir, region=region))

    def write(rows):
        records = [SimpleNamespace(as_dict=lambda row=row: row) for row in rows]
        adapter = SimpleNamespace(enrich=lambda *_: records, discover=lambda *_: records, report={})
        if kind == "report":
            adapter.report = {binding.id: {"label": rows[0]["z"]}}
        return enrich.enrich_code(ctx, object(), [{"vessel_id": "synthetic"}], {adapter_id: adapter})

    name = "enrich-code.json" if kind == "report" else f"{kind}.jsonl"
    return kind, run.dir / name, write


def test_serialization_failure_preserves_previous_file(evidence):
    kind, path, write = evidence
    path.write_bytes(BEFORE)
    path.chmod(0o600)
    bad_rows = [{"z": object()}] if kind == "report" else [ROWS[0], {"z": object()}]
    with pytest.raises(TypeError):
        write(bad_rows)
    assert path.read_bytes() == BEFORE
    assert not list(path.parent.glob(f".{path.name}.*.tmp"))


def test_io_failure_preserves_previous_file(evidence, monkeypatch):
    _, path, write = evidence
    path.write_bytes(BEFORE)
    path.chmod(0o600)
    replace = os.replace

    def fail_commit(src, dst, *args, **kwargs):
        if dst == path:
            raise OSError(errno.ENOSPC, "synthetic replacement failure")
        return replace(src, dst, *args, **kwargs)

    monkeypatch.setattr(os, "replace", fail_commit)
    with pytest.raises(OSError) as error:
        write(ROWS)
    assert error.value.errno == errno.ENOSPC
    assert path.read_bytes() == BEFORE
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert not list(path.parent.glob(f".{path.name}.*.tmp"))


def test_success_preserves_encoding_order_count_and_mode(evidence):
    kind, path, write = evidence
    for mode in (0o600, 0o640):
        if path.exists():
            path.chmod(mode)
        counts = write(ROWS)
        if kind == "report":
            doc = {"bindings": {"synthetic": {"label": "café"}}, "counts": counts,
                   "purged_places_facts": 0, "vessels": 1}
            expected = json.dumps(doc, sort_keys=True, indent=2) + "\n"
            assert counts == {"vessels": 1, "facts": 0, "flagged": 0, "imported": 2,
                              "purged": 0, "places_skipped": 0}
        else:
            rows = [{"vessel_id": "synthetic", **row} for row in ROWS] if kind == "facts" else ROWS
            expected = "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows)
            assert (counts if kind == "run" else counts[kind]) == 2
        assert path.read_bytes() == expected.replace("\n", os.linesep).encode("utf-8")
        assert stat.S_IMODE(path.stat().st_mode) == mode
