"""skippercast.report: attempt, byte-count and source-ratio cells cannot break their table rows."""
import json

import pytest

from skippercast import report, runs

BAD = "x|y\n### injected\\z"


def doc(**fields):
    base = {"schema_version": runs.SCHEMA_VERSION, "job": "refresh", "run_id": "7", "started_at": "2026-11-01T00:00:00Z",
            "status": "ok", "inputs": [], "outputs": [], "sources": {}}
    base.update(fields)
    return base


def row_with(text, prefix):
    return next(line for line in text.splitlines() if line.startswith(prefix))


def unescaped_pipes(line):
    return line.replace("\\\\", "").replace("\\|", "").count("|")


def damaged(site, value):
    if site == "attempt":
        return doc(run_attempt=value), "| 7 ", 6
    if site == "bytes":
        return doc(inputs=[{"path": "f.json", "bytes": value}]), "| f.json ", 4
    key = {"ok": "sources_ok", "total": "sources_total"}[site]
    fields = {"sources_ok": 1, "sources_total": 2, "status": "ok"}
    fields[key] = value
    return doc(regions={"r": fields}), "| r ", 6


@pytest.mark.parametrize("site", ["attempt", "bytes", "ok", "total"])
def test_raw_scalar_fields_cannot_break_table_rows(site):
    document, prefix, pipes = damaged(site, BAD)
    text = report.render(document)
    assert "\n### injected" not in text
    assert unescaped_pipes(row_with(text, prefix)) == pipes


FRAGMENT = {"attempt": "(attempt {})", "bytes": "{}", "ok": "{}/2", "total": "1/{}"}


@pytest.mark.parametrize("site", ["attempt", "bytes", "ok", "total"])
def test_scalar_cell_boundaries_use_existing_escaping(site):
    for value in ("a" * 298 + "|" + "b" * 5, "a" * 299 + "|" + "b" * 5, "a" * 298 + "||||"):
        document, prefix, pipes = damaged(site, value)
        line = row_with(report.render(document), prefix)
        assert unescaped_pipes(line) == pipes
        expected = report.cell(FRAGMENT[site].format(value))
        assert expected.endswith("…") == (len(FRAGMENT[site].format(value)) > report.MAX_CELL) and expected in line


def test_numeric_and_missing_scalar_controls_unchanged():
    assert "| 7 (attempt 2) |" in report.render(doc(run_attempt=2))
    assert "(attempt" not in report.render(doc(run_attempt=0))
    assert "(attempt" not in report.render(doc())
    files = [{"path": "a", "bytes": 12}, {"path": "b"}, {"path": "c", "bytes": None}, {"path": "d", "bytes": 0}]
    text = report.render(doc(inputs=files))
    assert [row_with(text, f"| {p} ").split(" | ")[1] for p in "abcd"] == ["12", "–", "None", "0"]
    lines = report.regions_table({"a": {"status": "ok", "sources_ok": 3, "sources_total": 4},
                                  "b": {"status": "ok", "sources_total": 0}, "c": {"status": "ok"}})
    assert [row_with("\n".join(lines), f"| {r} ").split(" | ")[2] for r in "abc"] == ["3/4", "–", "–"]


def test_append_summary_matches_safe_stdout(tmp_path, monkeypatch, capsys):
    paths = []
    for name, document in (("bad", damaged("attempt", BAD)[0]), ("good", doc(run_attempt=1))):
        path = tmp_path / f"{name}.json"
        path.write_text(json.dumps(document), encoding="utf-8")
        paths.append(path)
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    assert report.main([*map(str, paths), "--append-summary"]) == 0
    out = capsys.readouterr().out
    assert "\n### injected" not in out
    assert summary.read_text(encoding="utf-8") == out + "\n"
