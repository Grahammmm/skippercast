"""MGL-03: the offline seafloor parity harness (synthetic ledgers, injected runner, no seafloor science)."""
import copy
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import textwrap

import pytest

from tests._support import ROOT

SCRIPT = ROOT / "research" / "seafloor-parity" / "run_parity.py"
_spec = importlib.util.spec_from_file_location("run_parity_mgl03", SCRIPT)
parity = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(parity)

COMMIT_X = "a" * 40
ROW = "MGL-06"
GIT_ENV = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.invalid",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.invalid", GIT_CONFIG_GLOBAL=os.devnull)


def values(**over):
    base = {"tier1_km2": 59.014375, "selected_valid_km2": 56.089512589, "tier2_km2": 3.238533224,
            "polygons_by_grade": {"A": 0, "B": 3, "C": 184}, "habitat_count": 187, "held_by_reason": {}}
    base.update(over)
    return base


def ledger_doc():
    return {"schema_version": 1, "scope": "x", "totals": {"tier1_km2": 1}, "reaches": [
        {"id": "r1", "region": "x", **values()},
        {"id": "r2", "region": "x", **values(held_by_reason={"overlap-cdfw-mpa": 82}, habitat_count=149)}]}


def sh(cwd, *cmd):
    subprocess.run(cmd, cwd=cwd, check=True, capture_output=True, env=GIT_ENV)


def jwrite(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Rig:
    """A source git repo, a private row root with baseline + disposable checkout, and a fake launcher."""

    def __init__(self, tmp):
        self.parent = tmp / "private-runs"
        self.root = self.parent / ROW
        self.source = tmp / "source"
        self.checkout = self.root / "repo"
        self.baseline = self.root / "baseline"
        catalog = {"reaches": [{"id": "r1", "name": "one"}, {"id": "r2", "name": "two"}]}
        jwrite(self.source / "dist/data/seafloor-ledger.json", ledger_doc())
        jwrite(self.source / "catalog/reaches.json", catalog)
        sh(self.source, "git", "init", "-q")
        sh(self.source, "git", "add", ".")
        sh(self.source, "git", "commit", "-q", "-m", "base")
        commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=self.source, capture_output=True, text=True).stdout.strip()
        for rel, name in (("dist/data/seafloor-ledger.json", "seafloor-ledger.json"), ("catalog/reaches.json", "reaches.json")):
            (self.baseline).mkdir(parents=True, exist_ok=True)
            (self.baseline / name).write_bytes((self.source / rel).read_bytes())
        jwrite(self.baseline / "manifest.json", {"source_commit": commit, "ledger_sha256": sha(self.baseline / "seafloor-ledger.json"),
                                                  "reaches_sha256": sha(self.baseline / "reaches.json")})
        jwrite(self.checkout / "dist/data/seafloor-ledger.json", ledger_doc())
        jwrite(self.checkout / "catalog/reaches.json", catalog)
        (self.root / "checkout-commit.txt").write_text(COMMIT_X + "\n")
        jwrite(self.root / "reaches.json", ["r1", "r2"])
        self.output = self.root / "parity.jsonl"
        self.calls = []
        self.screen = {"status": "ready", "reasons": []}
        self.override = {}      # reach id -> values the fake run produces
        self.fail = {}          # reach id -> (returncode, stderr)
        self.private = set()
        self.mutate_baseline = None

    def argv(self, **over):
        opts = {"--row-id": ROW, "--source-checkout": str(self.source), "--checkout": str(self.checkout),
                "--baseline-dir": str(self.baseline), "--reaches-file": str(self.root / "reaches.json"),
                "--output": str(self.output), "--python": sys.executable}
        opts.update(over)
        return [x for kv in opts.items() for x in kv]

    def write_run(self, reach, vals, *, incomplete=False, corrupt=False):
        folder = self.checkout / "var/seafloor" / ("private-reaches" if reach in self.private else "reaches") / reach
        outputs = {}
        for name in parity.RECEIPT_OUTPUTS:
            (folder / name).parent.mkdir(parents=True, exist_ok=True)
            (folder / name).write_text(name + reach)
            outputs[name] = sha(folder / name)
        summary = {**vals, "status": "habitat-screened", "processing_incomplete": incomplete, "screen": self.screen}
        receipt = {"ledger_summary": summary, "outputs": outputs, "publication_prohibited": reach in self.private}
        jwrite(folder / "run.json", receipt)
        if corrupt:
            (folder / "cells.json").write_text("tampered")
        if reach not in self.private:
            data = json.loads((self.checkout / "dist/data/seafloor-ledger.json").read_text())
            for row in data["reaches"]:
                if row["id"] == reach:
                    row.update(vals)
            jwrite(self.checkout / "dist/data/seafloor-ledger.json", data)
        return {"unchanged": False, **summary}

    def runner(self, **flags):
        def run(argv, cwd, timeout):
            self.calls.append((list(argv), cwd, timeout))
            if argv[-1] == "--which":
                return 0, "resolved inside checkout: yes\n", ""
            reach = argv[-1]
            if self.mutate_baseline:
                (self.baseline / "reaches.json").write_text("{}")
            if reach in self.fail:
                code, err = self.fail[reach]
                return code, "", err
            vals = self.override.get(reach, json.loads((self.baseline / "seafloor-ledger.json").read_text())
                                     ["reaches"][int(reach[1:]) - 1])
            vals = {k: vals[k] for k in parity.FIELDS}
            return 0, json.dumps(self.write_run(reach, vals, **flags)), ""
        return run

    def go(self, runner=None, **over):
        return parity.main(self.argv(**over), runner=runner or self.runner(), private_parent=self.parent)

    def rows(self):
        return [json.loads(line) for line in self.output.read_text().splitlines()]


@pytest.fixture
def rig(tmp_path):
    return Rig(tmp_path)


def test_six_fields_exact_unordered_maps(rig):
    rig.override["r1"] = values(polygons_by_grade={"C": 184, "B": 3, "A": 0}, tier1_km2=59.014375,
                                selected_valid_km2=56.089512589)
    rig.override["r2"] = values(held_by_reason={"overlap-cdfw-mpa": 82}, habitat_count=149.0, tier2_km2=3.238533224)
    assert rig.go() == 0
    rows = rig.rows()
    assert [r["reach_id"] for r in rows] == ["r1", "r2"]
    assert [r["status"] for r in rows] == ["exact", "exact"]
    assert set(rows[0]) == {"schema_version", "row_id", "reach_id", "status", "baseline", "actual", "command", "returncode",
                            "unchanged", "differences", "findings", "logs", "integrity"}
    assert rows[0]["differences"] == [] and list(rows[0]["baseline"]["values"]) == list(parity.FIELDS)
    assert rows[0]["actual"]["commit_verification"] == "declared"


def test_every_difference_named_without_rounding(rig):
    rig.override["r1"] = values(tier1_km2=59.0143751, selected_valid_km2=1, tier2_km2=0, habitat_count=1,
                                polygons_by_grade={"A": 0, "B": 4, "C": 184}, held_by_reason={"new-reason": 2})
    rig.override["r2"] = values(held_by_reason={}, habitat_count=149)
    before = sha(rig.baseline / "seafloor-ledger.json")
    assert rig.go() == 1
    first, second = rig.rows()
    assert [d["path"] for d in first["differences"]] == ["tier1_km2", "selected_valid_km2", "tier2_km2",
                                                         "polygons_by_grade.B", "habitat_count", "held_by_reason.new-reason"]
    assert first["differences"][0]["baseline"] == 59.014375 and first["differences"][0]["actual"] == 59.0143751
    added = first["differences"][-1]
    assert (added["baseline_present"], added["actual_present"], added["actual"]) == (False, True, 2)
    removed = [d for d in second["differences"] if d["path"] == "held_by_reason.overlap-cdfw-mpa"][0]
    assert (removed["baseline_present"], removed["actual_present"], removed["baseline"]) == (True, False, 82)
    assert first["status"] == "different" and sha(rig.baseline / "seafloor-ledger.json") == before


@pytest.mark.parametrize("bad", [
    {"tier1_km2": None}, {"tier1_km2": True}, {"tier1_km2": -1}, {"tier1_km2": float("nan")},
    {"habitat_count": 1.5}, {"habitat_count": -1}, {"habitat_count": True},
    {"polygons_by_grade": {"A": 0, "B": 1}}, {"held_by_reason": {"x": -1}}, {"held_by_reason": []}])
def test_malformed_values_are_errors_not_zero(bad):
    with pytest.raises(parity.Evidence):
        parity.six_fields({**values(), **bad}, "t")
    row = values()
    del row["tier2_km2"]
    with pytest.raises(parity.Evidence):
        parity.six_fields(row, "t")


def test_duplicate_ids_and_schema_are_errors():
    doc = ledger_doc()
    doc["reaches"].append(copy.deepcopy(doc["reaches"][0]))
    with pytest.raises(parity.Evidence, match="duplicate-id"):
        parity.ledger_rows(doc, "t")
    doc = ledger_doc()
    doc["schema_version"] = 2
    with pytest.raises(parity.Evidence, match="unsupported-schema"):
        parity.ledger_rows(doc, "t")


@pytest.mark.parametrize("reaches", [[], ["r1", "r1"], ["nope"], [""], "r1", ["../x"]])
def test_bad_reach_lists_refuse_before_any_run(rig, reaches, capsys):
    jwrite(rig.root / "reaches.json", reaches)
    assert rig.go() == 2
    assert rig.calls == [] and not rig.output.exists()
    assert "refused" in capsys.readouterr().err


def test_private_boundary_and_alias_refusal(rig, tmp_path):
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    (rig.root / "link").symlink_to(outside)
    cases = [
        {"--source-checkout": str(rig.checkout)},
        {"--checkout": str(outside)},
        {"--output": str(outside / "o.jsonl")},
        {"--output": str(rig.root / ".." / "o.jsonl")},
        {"--output": str(rig.root / "link" / "o.jsonl")},
        {"--output": str(rig.baseline / "o.jsonl")},
        {"--output": str(rig.root / "reaches.json")},
        {"--baseline-dir": str(rig.checkout / "dist")},
    ]
    for over in cases:
        assert rig.go(**over) == 2, over
    assert rig.calls == [] and not rig.output.exists()
    rig.output.write_text("old")
    assert rig.go() == 2 and rig.output.read_text() == "old" and rig.calls == []


def test_symlinked_row_root_is_never_the_confinement_root(rig, tmp_path):
    outside = tmp_path / "outside"
    rig.root.rename(outside)
    rig.root.symlink_to(outside)         # private-runs/MGL-06 -> outside, everything lives behind the link
    assert rig.go() == 2
    assert rig.go(**{"--checkout": str(outside / "repo"), "--baseline-dir": str(outside / "baseline"),
                     "--reaches-file": str(outside / "reaches.json"), "--output": str(outside / "p.jsonl")}) == 2
    assert rig.calls == [] and not rig.output.exists() and not (outside / "p.jsonl").exists()
    assert not (outside / "logs").exists()


def test_symlinked_mutable_paths_refuse(rig, tmp_path):
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    (rig.checkout / "var").symlink_to(outside)
    assert rig.go() == 2 and rig.calls == []
    (rig.checkout / "var").unlink()
    (rig.checkout / "dist").rename(rig.root / "dist-moved")
    (rig.checkout / "dist").symlink_to(rig.root / "dist-moved")
    assert rig.go() == 2 and rig.calls == []


@pytest.mark.parametrize("tree", ["reaches", "private-reaches"])
@pytest.mark.parametrize("kind", ["dir-link", "dangling-link", "file-link"])
def test_symlinked_reach_destination_refuses_before_any_child(rig, tmp_path, tree, kind):
    outside = tmp_path / "outside"
    outside.mkdir()
    folder = rig.checkout / "var/seafloor" / tree / "r2"      # requested reach, not the first
    folder.parent.mkdir(parents=True)
    if kind == "dir-link":
        folder.symlink_to(outside)
    elif kind == "dangling-link":
        folder.symlink_to(tmp_path / "does-not-exist")
    else:
        folder.mkdir()
        (outside / "run.json").write_text("outside")
        (folder / "run.json").symlink_to(outside / "run.json")
    before = sorted(p.name for p in outside.iterdir())
    assert rig.go() == 2
    assert rig.calls == [] and not rig.output.exists()          # no --which, no run, no output
    assert sorted(p.name for p in outside.iterdir()) == before
    assert not (outside / "coverage-checkpoint.json").exists() and not (rig.root / "logs").exists()
    if kind == "file-link":
        assert (outside / "run.json").read_text() == "outside"


def test_real_reach_directories_inside_the_checkout_are_admitted(rig):
    for tree in ("reaches", "private-reaches"):
        (rig.checkout / "var/seafloor" / tree / "r1").mkdir(parents=True)
    assert rig.go() == 0 and len(rig.calls) == 3


def test_baseline_must_be_committed_identity(rig):
    manifest = json.loads((rig.baseline / "manifest.json").read_text())
    for change in ({"ledger_sha256": "0" * 64}, {"source_commit": "b" * 40}, {"extra": 1}):
        jwrite(rig.baseline / "manifest.json", {**manifest, **change})
        assert rig.go() == 2, change
    (rig.baseline / "manifest.json").unlink()
    assert rig.go() == 2
    jwrite(rig.baseline / "manifest.json", manifest)
    (rig.baseline / "seafloor-ledger.json").write_text(json.dumps({**ledger_doc(), "scope": "tampered"}))
    assert rig.go() == 2 and rig.calls == [] and not rig.output.exists()


def test_launcher_argv_and_one_call_per_reach(rig):
    assert rig.go() == 0
    which, *runs = rig.calls
    assert which[0] == [sys.executable, "-B", parity.LAUNCHER, "--checkout", str(rig.checkout), "--which"]
    assert parity.LAUNCHER == os.path.expanduser("~/agent-work/bin/seafloor-cli.py")
    assert [c[0] for c in runs] == [[sys.executable, "-B", parity.LAUNCHER, "--checkout", str(rig.checkout), "run", "--reach", r]
                                    for r in ("r1", "r2")]
    assert all(c[1] == str(rig.checkout) and c[2] == 1800 for c in runs)
    assert not any(flag in a for c in runs for a in c[0] for flag in ("--fetch", "--force", "--physical-only"))


@pytest.mark.parametrize("failure", [(1, "missing substrate zip"), (None, "")])
def test_failed_child_cannot_match_stale_ledger(rig, failure):
    # Yesterday's row and receipt are already equal to the baseline.
    rig.write_run("r1", values())
    rig.fail["r1"] = failure
    assert rig.go() == 2
    first, second = rig.rows()
    assert first["status"] == "error" and second["status"] == "not_run"
    assert first["findings"][0]["code"] in ("child-failed", "timeout")
    assert len(rig.calls) == 2    # --which and r1 only, no retry, r2 never started
    assert first["actual"] is None and (rig.root / first["logs"]["stderr"]).read_text() == failure[1]


def test_which_resolution_failure_refuses(rig):
    assert rig.go(runner=lambda argv, cwd, timeout: (1, "resolved inside checkout: NO", "")) == 2
    assert not rig.output.exists()


def _first_row(rig, mutate=None, **flags):
    run = rig.runner(**flags)

    def wrapped(argv, cwd, timeout):
        code, out, err = run(argv, cwd, timeout)
        return (code, mutate(out), err) if mutate and argv[-1] == "r1" else (code, out, err)
    return wrapped


@pytest.mark.parametrize("name, mutate, flags, code", [
    ("malformed-stdout", lambda out: "not json", {}, "malformed-stdout"),
    ("disagree", lambda out: json.dumps({**json.loads(out), "habitat_count": 1}), {}, "evidence-disagree"),
    ("incomplete", None, {"incomplete": True}, "processing-incomplete"),
    ("corrupt", None, {"corrupt": True}, "receipt-hash"),
])
def test_completed_evidence_must_agree(rig, name, mutate, flags, code):
    assert rig.go(runner=_first_row(rig, mutate, **flags)) == 2
    first = rig.rows()[0]
    assert first["status"] == "error" and first["findings"][0]["code"] == code and first["actual"] is None


def test_derived_ledger_row_must_match_receipt(rig):
    run = rig.runner()

    def drift(argv, cwd, timeout):
        result = run(argv, cwd, timeout)
        if argv[-1] == "r1":
            data = json.loads((rig.checkout / "dist/data/seafloor-ledger.json").read_text())
            data["reaches"][0]["habitat_count"] = 2
            jwrite(rig.checkout / "dist/data/seafloor-ledger.json", data)
        return result
    assert rig.go(runner=drift) == 2
    assert rig.rows()[0]["findings"][0]["code"] == "evidence-disagree"


def test_unchanged_reuse_and_private_source_are_handled(rig):
    run = rig.runner()

    def reuse(argv, cwd, timeout):
        code, out, err = run(argv, cwd, timeout)
        return (code, json.dumps({**json.loads(out), "unchanged": True}), err) if argv[-1] != "--which" else (code, out, err)
    assert rig.go(runner=reuse) == 0
    assert all(r["unchanged"] is True for r in rig.rows())
    rig.output.unlink()
    for log in (rig.root / "logs").iterdir():
        log.rename(log.with_suffix(".old"))
    shutil.rmtree(rig.checkout / "var/seafloor/reaches/r1")    # a private run leaves no public receipt for r1
    rig.private.add("r1")
    assert rig.go() == 1
    first = rig.rows()[0]
    assert first["status"] == "held" and first["actual"]["publication_prohibited"] is True
    assert first["findings"][0]["code"] == "private-source-only"


def test_both_public_and_private_receipts_are_ambiguous_whatever_the_mtime(rig):
    """Reuse does not rewrite a receipt, so a newer public receipt must never outrank an older private one."""
    run = rig.runner()
    rig.private.add("r1")
    private_summary = rig.write_run("r1", values())      # the receipt the unchanged run actually used
    rig.private.discard("r1")
    rig.write_run("r1", values())                         # newer public receipt, same six fields
    old = rig.checkout / "var/seafloor/private-reaches/r1/run.json"
    os.utime(old, ns=(1, 1))
    assert (rig.checkout / "var/seafloor/reaches/r1/run.json").stat().st_mtime_ns > old.stat().st_mtime_ns

    def reuse(argv, cwd, timeout):
        if argv[-1] == "--which":
            return run(argv, cwd, timeout)
        return 0, json.dumps({**private_summary, "unchanged": True}), ""
    assert rig.go(runner=reuse) == 2
    first = rig.rows()[0]
    assert first["status"] == "error" and first["findings"][0]["code"] == "receipt-ambiguous"
    assert first["actual"] is None and rig.rows()[1]["status"] == "not_run"


def test_screen_held_is_not_exact_success(rig):
    rig.screen = {"status": "held", "reasons": ["screen-stale"]}
    assert rig.go() == 1
    rows = rig.rows()
    assert [r["status"] for r in rows] == ["held", "held"]
    assert rows[0]["differences"] == [] and rows[0]["actual"]["screen_reasons"] == ["screen-stale"]
    assert rows[0]["findings"][0]["code"] == "screen-not-ready"


def test_baseline_mutation_during_run_is_integrity_failure(rig):
    rig.mutate_baseline = True
    assert rig.go() == 2
    first, second = rig.rows()
    assert first["status"] == "error" and first["integrity"]["baseline_unchanged"] is False
    assert second["status"] == "not_run" and len(rig.calls) == 2
    assert (rig.baseline / "reaches.json").read_text() == "{}"    # never repaired


def test_source_checkout_change_is_integrity_failure(rig):
    run = rig.runner()

    def dirty(argv, cwd, timeout):
        (rig.source / "stray.txt").write_text("x")
        return run(argv, cwd, timeout)
    assert rig.go(runner=dirty) == 2
    assert rig.rows()[0]["integrity"]["source_checkout_unchanged"] is False


def test_offline_cli_fixture_end_to_end(rig):
    """The real CLI/parser/JSONL writer in a subprocess, with only the child runner replaced."""
    rig.override["r1"] = values(habitat_count=1)
    driver = rig.root.parent / "driver.py"
    driver.write_text(textwrap.dedent(f"""
        import importlib.util, json, sys
        spec = importlib.util.spec_from_file_location("rp", {str(SCRIPT)!r})
        rp = importlib.util.module_from_spec(spec); spec.loader.exec_module(rp)
        base = json.load(open({str(rig.baseline / 'seafloor-ledger.json')!r}))['reaches']
        def runner(argv, cwd, timeout):
            if argv[-1] == '--which':
                return 0, 'resolved inside checkout: yes', ''
            return 1, '', 'stub launcher: no science in this test'
        sys.exit(rp.main(sys.argv[1:], runner=runner, private_parent={str(rig.parent)!r}))
    """))
    done = subprocess.run([sys.executable, "-B", str(driver), *rig.argv()], capture_output=True, text=True)
    assert done.returncode == 2 and done.stdout.startswith(str(rig.output))
    assert [r["status"] for r in rig.rows()] == ["error", "not_run"]
    # Real exit 1 path (differences) through the same in-process entry, plus the --help surface.
    rig.output.unlink()
    for log in (rig.root / "logs").iterdir():
        log.rename(log.with_suffix(".old"))
    assert rig.go() == 1
    help_text = subprocess.run([sys.executable, "-B", str(SCRIPT), "--help"], capture_output=True, text=True)
    assert help_text.returncode == 0
    for option in ("--row-id", "--source-checkout", "--checkout", "--baseline-dir", "--reaches-file", "--output", "--python"):
        assert option in help_text.stdout


def test_production_cli_cannot_override_private_parent():
    assert str(parity.PRIVATE_PARENT) == os.path.expanduser("~/agent-work/reports/seafloor-agg/private-runs")
    assert "--private-parent" not in parity.parser().format_help()
    with pytest.raises(SystemExit):
        parity.parser().parse_args(["--private-parent", "/tmp"])
