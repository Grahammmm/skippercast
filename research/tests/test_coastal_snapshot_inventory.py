"""SC-4 source census and complete disposition coverage; no private data needed."""
from collections import Counter
import hashlib
import json
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
    assert len(dispositions) == len({path for path, _, _ in dispositions}) == len(absent) == 17
    assert {path for path, _, _ in dispositions} == absent
    assert Counter(decision for _, decision, _ in dispositions) == {"retire": 12, "needed-by-stage": 5}
    assert all(len(reason) > 80 for _, _, reason in dispositions)
    assert "/home/" not in text + REPORT.read_text()
