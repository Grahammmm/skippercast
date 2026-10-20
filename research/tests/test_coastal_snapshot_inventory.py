"""SC-4 source census and complete disposition coverage; no private data needed."""
import ast
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re
import sys

import pytest

from research.lib.paths import ROOT
from research.scripts import audit_coastal_snapshot_inventory as audit

REPORT = ROOT / "docs/engineering/audits/coastal-snapshot-2026-10-20.json"


@pytest.fixture
def source(tmp_path, monkeypatch):
    base = tmp_path / audit.PREFIX
    (base / "resources").mkdir(parents=True)
    for name, data in {"same.py": b"same\n", "changed.py": b"after\n", "discover.py": b"raise RuntimeError('never import')\n"}.items():
        (base / name).write_bytes(data)
    (base / "resources/new.schema.json").write_text("{}")
    for name in ("scripts/build_schema_resources.py", "tests/unit/test_fixture.py",
                 "research/tests/test_runtime.py", "tests/var/ignored.py",
                 "var/never_read.py", "skills/hermes/skippercast-coastal/SKILL.md"):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("raise RuntimeError('never execute snapshot')\n")
    tracked = {
        audit.PREFIX + "same.py": b"same\n",
        audit.PREFIX + "changed.py": b"before\n",
        audit.SKILL_COUNTERPARTS["discover.py"]: b"old skill helper\n",
    }

    def fake_git(repo, *args):
        if args[0] == "rev-parse":
            return b"a" * 40 + b"\n"
        if args[0] == "ls-tree":
            return ("\n".join(tracked) + "\n").encode()
        assert args[0] == "show"
        return tracked[args[1].split(":", 1)[1]]

    monkeypatch.setattr(audit, "git", fake_git)
    return tmp_path, base


def test_census_reads_without_importing_and_is_stable(source):
    root, _ = source
    result = audit.inventory(root, root, "fixture")
    assert result == audit.inventory(root, root, "fixture")
    assert result["counts"] == {"different": 1, "identical": 1, "snapshot-only": 1}
    row = next(r for r in result["modules"] if r["comparison"] == "snapshot-only")
    assert row["path"] == audit.PREFIX + "discover.py"
    assert row["skill_counterpart"]["byte_identical_to_snapshot"] is False
    assert len(result["snapshot_only_resources"]) == 1
    assert result["snapshot_only_counts"] == {
        "coastal_modules": 1, "outside_package_modules": 1,
        "tests": 1, "research_tests": 1, "python_total": 4,
    }
    assert [r["path"] for r in result["snapshot_only_outside_package"]] == ["scripts/build_schema_resources.py"]
    assert [r["path"] for r in result["snapshot_only_tests"]] == [
        "research/tests/test_runtime.py", "tests/unit/test_fixture.py",
    ]
    assert len(result["snapshot_only_documents"]) == 1
    assert str(root) not in json.dumps(result)


def test_missing_snapshot_fails(source):
    root, _ = source
    with pytest.raises(ValueError, match="missing"):
        audit.inventory(root, root / "missing", "fixture")


def test_symlink_source_fails(source):
    root, base = source
    (base / "alias.py").symlink_to(base / "same.py")
    with pytest.raises(ValueError, match="symlink"):
        audit.inventory(root, root, "fixture")


@pytest.mark.parametrize("name", ["tests/alias.py", "scripts/alias.py"])
def test_supplemental_symlink_fails(source, name):
    root, base = source
    (root / name).symlink_to(base / "same.py")
    with pytest.raises(ValueError, match="symlink"):
        audit.inventory(root, root, "fixture")


def test_symlink_directory_fails(source):
    root, base = source
    (root / "tests/alias").symlink_to(base, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink source directory"):
        audit.inventory(root, root, "fixture")


def test_missing_resources_fails_clearly(source):
    root, base = source
    (base / "resources").rename(base / "old-resources")
    with pytest.raises(ValueError, match="resources directory missing"):
        audit.inventory(root, root, "fixture")


def test_nested_resources_fail_closed(source):
    root, base = source
    (base / "resources/nested").mkdir()
    with pytest.raises(ValueError, match="nested resource"):
        audit.inventory(root, root, "fixture")


@pytest.mark.parametrize("name", ["tests/unit/test_fixture.py", "research/tests/test_runtime.py",
                                  "scripts/build_schema_resources.py",
                                  "skills/hermes/skippercast-coastal/SKILL.md"])
def test_supplemental_hash_detects_drift(source, name):
    root, _ = source
    before = audit.inventory(root, root, "fixture")
    (root / name).write_text("changed source\n")
    assert before != audit.inventory(root, root, "fixture")


def test_check_detects_changed_source(source, monkeypatch, capsys):
    root, base = source
    saved = root / "inventory.json"
    saved.write_text(json.dumps(audit.inventory(root, root, "fixture")))
    monkeypatch.setattr(sys, "argv", ["audit", "--repo", str(root), "--snapshot", str(root),
                                      "--main-ref", "fixture", "--check", str(saved)])
    audit.main()
    assert "PASS: source inventory matches" in capsys.readouterr().out
    (base / "same.py").write_text("changed after capture\n")
    with pytest.raises(SystemExit, match="differs"):
        audit.main()


def test_committed_inventory_and_dispositions_are_complete():
    evidence = json.loads(REPORT.read_text())
    rows = evidence["modules"]
    assert len(rows) == len({row["path"] for row in rows}) == 68
    assert Counter(row["comparison"] for row in rows) == evidence["counts"] == {
        "different": 20, "identical": 31, "snapshot-only": 17,
    }
    manifest = "".join(row["path"] + "\t" + row["snapshot"]["sha256"] + "\n" for row in rows)
    assert hashlib.sha256(manifest.encode()).hexdigest() == evidence["source_manifest_sha256"]
    for row in rows:
        assert row["path"].startswith(audit.PREFIX)
        assert re.fullmatch(r"[0-9a-f]{64}", row["snapshot"]["sha256"])
        assert (row["main"] is None) == (row["comparison"] == "snapshot-only")
    text = REPORT.with_suffix(".md").read_text()
    dispositions = re.findall(r"^\| `([^`]+\.py)` \| (retire|needed-by-stage) \| (.+) \|$", text, re.M)
    absent = {row["path"].removeprefix(audit.PREFIX) for row in rows if row["comparison"] == "snapshot-only"}
    absent.update(row["path"] for row in evidence["snapshot_only_outside_package"])
    assert len(dispositions) == len({path for path, _, _ in dispositions}) == len(absent) == 20
    assert {path for path, _, _ in dispositions} == absent
    assert Counter(decision for _, decision, _ in dispositions) == {"retire": 14, "needed-by-stage": 6}
    assert all(len(reason) > 80 for _, _, reason in dispositions)
    assert "/home/" not in text + REPORT.read_text()


def test_committed_supplemental_counts_and_test_handoff():
    evidence = json.loads(REPORT.read_text())
    assert evidence["schema"] == "coastal-snapshot-inventory-v2"
    assert evidence["supplemental_scope"] == [name + "/**/*.py" for name in audit.SOURCE_DIRS]
    assert evidence["excluded_directories"] == sorted(audit.EXCLUDED_DIRS)
    outside = evidence["snapshot_only_outside_package"]
    tests = evidence["snapshot_only_tests"]
    assert {r["path"] for r in outside} == {
        "scripts/build_schema_resources.py", "skills/hermes/skippercast-coastal/tool.py",
        "skills/skippercast-discover-coastal-sources/scripts/asset_selection.py",
    }
    counts = {
        "coastal_modules": sum(r["comparison"] == "snapshot-only" for r in evidence["modules"]),
        "outside_package_modules": len(outside),
        "tests": sum(r["path"].startswith("tests/") for r in tests),
        "research_tests": sum(r["path"].startswith("research/tests/") for r in tests),
    }
    counts["python_total"] = sum(counts.values())
    assert counts == evidence["snapshot_only_counts"] == {
        "coastal_modules": 17, "outside_package_modules": 3,
        "tests": 78, "research_tests": 1, "python_total": 99,
    }
    assert len(tests) == len({r["path"] for r in tests}) == 79
    assert [r["path"] for r in tests if r["path"].startswith("research/")] == [
        "research/tests/test_coastal_four128_runtime.py",
    ]
    assert [r["path"] for r in evidence["snapshot_only_documents"]] == list(audit.SUPPORTING_DOCUMENTS)
    for row in outside + tests + evidence["snapshot_only_documents"]:
        assert re.fullmatch(r"[0-9a-f]{64}", row["sha256"])
        assert isinstance(row["bytes"], int) and row["bytes"] > 0
    text = REPORT.with_suffix(".md").read_text()
    table = text.split("| Candidate | Required test files |", 1)[1].split("In particular,", 1)[0]
    handoffs = re.findall(r"^\| `([^`]+\.py)` \| (.+) \| (.+) \|$", table, re.M)
    assert {r[0] for r in handoffs} == {
        "discover.py", "formats.py", "gsf_resume.py", "holds.py", "quality.py",
    }
    for _, required, shared in handoffs:
        paths = re.findall(r"`([^`]+\.py)`", required + shared)
        assert len(paths) >= 3
        assert set(paths) <= {r["path"] for r in tests}


def coastal_references(source):
    """Find all imported names and qualified references without executing source."""
    names = {
        alias.name
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.ImportFrom) and node.module == "skippercast.coastal"
        for alias in node.names
    }
    # Include dotted imports, attributes and string-based patch/import targets.
    names.update(re.findall(r"\bskippercast\.coastal\.([A-Za-z_]\w*)\b", source))
    return names


def test_coastal_references_include_all_names_and_nested_imports():
    source = '''
from skippercast.coastal import discover as d, quality as q
def nested():
    from skippercast.coastal import (
        formats as f,
        gsf_resume,
    )
import skippercast.coastal.holds as h
skippercast.coastal.quality.inspect_native()
target = "skippercast.coastal.formats.inspect_gsf"
raise RuntimeError("source must never execute")
'''
    assert coastal_references(source) == {
        "discover", "quality", "formats", "gsf_resume", "holds",
    }


def test_snapshot_importers_are_in_candidate_handoffs():
    snapshot_path = os.environ.get("SKIPPERCAST_COASTAL_SNAPSHOT", "")
    if not snapshot_path or not Path(snapshot_path).exists():
        pytest.skip("Retained coastal source snapshot unavailable; committed inventory checked separately")
    snapshot = Path(snapshot_path)
    evidence = json.loads(REPORT.read_text())
    text = REPORT.with_suffix(".md").read_text()
    table = text.split("| Candidate | Required test files |", 1)[1].split("In particular,", 1)[0]
    handoffs = re.findall(r"^\| `([^`]+\.py)` \| (.+) \| (.+) \|$", table, re.M)
    candidates = {
        name.removesuffix(".py"): set(re.findall(r"`([^`]+\.py)`", required + shared))
        for name, required, shared in handoffs
    }
    missing = []
    for row in evidence["snapshot_only_tests"]:
        source = audit.source_bytes(snapshot / row["path"], snapshot)
        assert audit.identity(source) == {key: row[key] for key in ("bytes", "sha256")}, row["path"]
        references = coastal_references(source.decode("utf-8"))
        for candidate, paths in candidates.items():
            if candidate in references and row["path"] not in paths:
                missing.append(f"{candidate}.py: {row['path']}")
    assert not missing, "Missing snapshot importer handoffs:\n" + "\n".join(missing)
