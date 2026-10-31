import hashlib
import importlib.util
import json
from types import SimpleNamespace

import pytest

from tests._support import ROOT

SCRIPT = ROOT / "skills/skippercast-region-publish/scripts/region_publish.py"
spec = importlib.util.spec_from_file_location("region_publish", SCRIPT)
rp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rp)
SRC = {"s-a": {"review_status": "approved", "name": "Survey A"}, "s-c": {"review_status": "candidate", "name": "Survey C"}}
ROWS = ",".join(rp.HEADER) + "\nother-bay,build,built,none,r0,,,,,\nsyn-bay,review,built,none,r0,,,,,\n"
OLD = "syn-bay,review,built,none,r0,,,,,"
PRIOR = {".git/HEAD": "", "src/skippercast/platform/build.py": "", "catalog/depth-contours/syn-bay.geojson": "prior\n",
         "dist/regions/syn-bay/depth-contours.geojson": "prior\n", "README.md": "| Syn Bay | `preview` |\n"}

def tree(root):
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(root.rglob("*")) if p.is_file()}

def world(base, source="s-a", family="openai", sha=None, stamp=False):
    repo, run, ledger = base / "repo", base / "run-20261105", base / "LEDGER.csv"
    for rel, text in PRIOR.items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(text)
    prov = {"sources": [{"source_id": source, "sha256": "a" * 64, "survey_date": "2008", "vertical_datum": "MLLW"}], "sources_omitted": []}
    out = json.dumps({"type": "FeatureCollection", "provenance": prov | ({"publication_held": True} if stamp else {}), "features": []}).encode()
    (run / "candidate").mkdir(parents=True)
    (run / "candidate/syn-bay.geojson").write_bytes(out)
    outputs = [{"path": "candidate/syn-bay.geojson", "sha256": hashlib.sha256(out).hexdigest()}]
    identity = hashlib.sha256(json.dumps(sorted([o['path'], o['sha256']] for o in outputs), separators=(',', ':')).encode()).hexdigest()
    (run / "BUILD.json").write_text(json.dumps({"region_id": "syn-bay", "build_sha256": identity, "run": {"author_family": "Anthropic"}, "outputs": outputs}))
    (run / "REVIEW.md").write_text(f"Build-SHA256: {sha or identity}\nReviewer-Runtime: gpt-test\nReviewer-Family: {family}\n| visual | not-visually-inspected | none |\nOverall: PASS\n")
    ledger.write_text(ROWS)
    return repo, run, ledger

def runner(mode=None):
    """Stands in for region_review.py --check and platform.build (dist = copy of the catalog file); `drift` changes the 2nd build, `touch` edits README.md."""
    builds = []

    def run(cmd, cwd=None, env=None):
        if cmd[1].endswith("region_review.py"):
            return SimpleNamespace(returncode=0, stdout="REVIEW OK syn-bay PASS\n")
        assert env["PYTHONPATH"] == str(cwd / "src") and cmd[2:] == ["skippercast.platform.build"]
        builds.append(1)
        (cwd / "dist/regions/syn-bay/depth-contours.geojson").write_bytes((cwd / "catalog/depth-contours/syn-bay.geojson").read_bytes() + (b"x" if mode == "drift" and len(builds) == 2 else b""))
        if mode == "touch":
            (cwd / "README.md").write_text("changed by the build\n")
        return SimpleNamespace(returncode=0, stdout="")
    return run

def publish(w, status="preview", mode=None):
    return rp.main([str(w[1]), "--repo", str(w[0]), "--ledger", str(w[2])], run=runner(mode), loader=lambda root, rid: ({"id": rid, "name": "Syn Bay", "status": status}, SRC))

def test_approved_cross_family_run_publishes_and_repeats_byte_for_byte(tmp_path):
    a, b = world(tmp_path / "a"), world(tmp_path / "b")
    assert publish(a) == 0 and publish(b) == 0
    text = (a[1] / "PUBLISH.md").read_text()
    assert (a[0] / "catalog/depth-contours/syn-bay.geojson").read_bytes() == (a[1] / "candidate/syn-bay.geojson").read_bytes()
    assert "## PR body" in text and "## CHANGELOG line" in text and "phone capture not visually inspected" in text and "Not for navigation" in text
    identity = json.loads((a[1] / "BUILD.json").read_text())["build_sha256"]
    assert a[2].read_text() == ROWS.replace(OLD, "syn-bay,publish,reviewed,none,run-20261105," + identity + ",PASS (visual not inspected),gpt-test,,")
    assert tree(a[0]) == tree(b[0]) and text == (b[1] / "PUBLISH.md").read_text() and a[2].read_bytes() == b[2].read_bytes()

@pytest.mark.parametrize("kwargs,status,mode,reason", [({"source": "s-c"}, "preview", None, "source-candidate:s-c"), ({}, "draft", None, "region-draft"),
                                                       ({"family": " ANTHROPIC "}, "preview", None, "review-family"), ({"sha": "c" * 64}, "preview", None, "review-sha-mismatch"),
                                                       ({"stamp": True}, "preview", None, "publication-held"), ({}, "preview", "drift", "build-not-reproducible"),
                                                       ({}, "preview", "touch", "build-touched:README.md")])
def test_each_failed_rule_holds_with_its_reason_and_leaves_the_repo_untouched(tmp_path, kwargs, status, mode, reason):
    w = world(tmp_path, **kwargs)
    before = tree(w[0])
    assert publish(w, status, mode) == 1
    assert tree(w[0]) == before and f"HELD: {reason}\n" in (w[1] / "PUBLISH.md").read_text()
    identity = json.loads((w[1] / "BUILD.json").read_text())["build_sha256"]
    assert w[2].read_text() == ROWS.replace(OLD, f"syn-bay,review,held,{reason},run-20261105,{identity},PASS,gpt-test,,")

def test_changed_candidate_with_updated_output_hash_cannot_reuse_review(tmp_path):
    w = world(tmp_path)
    before = tree(w[0])
    candidate = w[1] / "candidate/syn-bay.geojson"
    changed = json.loads(candidate.read_text())
    changed["provenance"]["sources"][0]["survey_date"] = "2009"
    candidate.write_text(json.dumps(changed))
    build_path = w[1] / "BUILD.json"
    build = json.loads(build_path.read_text())
    build["outputs"][0]["sha256"] = hashlib.sha256(candidate.read_bytes()).hexdigest()
    build_path.write_text(json.dumps(build))
    assert publish(w) == 1
    assert "HELD: build-sha-mismatch\n" in (w[1] / "PUBLISH.md").read_text()
    assert ",held,build-sha-mismatch," in w[2].read_text()
    assert tree(w[0]) == before


def test_script_is_file_only_and_record_pr_sets_three_fields(tmp_path):
    assert not [t for t in ("git ", '"git"', "gh ", '"gh"', "wrangler", "push", "urllib", "http") if t in SCRIPT.read_text()]
    w = world(tmp_path)
    assert rp.main(["--record-pr", str(w[1]), "--pr", "1234", "--published-at", "2026-11-05", "--ledger", str(w[2])]) == 0
    assert w[2].read_text() == ROWS.replace(OLD, "syn-bay,review,published,none,r0,,,,1234,2026-11-05")


def test_crlf_ledger_keeps_unrelated_rows_byte_identical(tmp_path):
    w = world(tmp_path)
    crlf = ROWS.replace("\n", "\r\n").encode()
    w[2].write_bytes(crlf)
    assert publish(w) == 0
    new = w[2].read_bytes().split(b"\r\n")
    assert new[:2] == crlf.split(b"\r\n")[:2] and new[2] != crlf.split(b"\r\n")[2] and b"\n" not in b"".join(new)
    assert rp.main(["--record-pr", str(w[1]), "--pr", "7", "--ledger", str(w[2])]) == 0
    assert w[2].read_bytes().split(b"\r\n")[:2] == new[:2] and b"\n" not in b"".join(w[2].read_bytes().split(b"\r\n"))


FROZEN = "5041f8621bc79e5fb506c6503ea6135d0e328ea56f22eb4b9a778dfdc95903c9"  # PUBLISH.md of world() from the pre-EC9 script
EC_SHA = "e" * 64


def ec_world(base, deepened=0, block=True, tree_=True, check=(0, "EC OK 2 rows\n"), sha=EC_SHA, output=True, use="publish"):
    """world() plus an EC run (ec/s-a/EC-APPLY.json, EC.json, INTAKE.csv, BUILD.json ec, one unresolved-area feature); publishes it.
    The fake runner answers region_correct.py --check with `check`. Returns (world, exit code, --check calls, repo tree before)."""
    w = world(base)
    candidate, build_path, review = w[1] / "candidate/syn-bay.geojson", w[1] / "BUILD.json", w[1] / "REVIEW.md"
    doc = json.loads(candidate.read_text())
    doc["features"] = [{"type": "Feature", "geometry": None, "properties": {"kind": "unresolved-area", "reason": "hole", "blocks": 2}},
                       {"type": "Feature", "geometry": None, "properties": {"kind": "contour", "blocks": 9}}]
    candidate.write_text(json.dumps(doc))
    outputs = [{"path": "candidate/syn-bay.geojson", "sha256": hashlib.sha256(candidate.read_bytes()).hexdigest()}] if output else []
    identity = hashlib.sha256(json.dumps(sorted([o["path"], o["sha256"]] for o in outputs), separators=(",", ":")).encode()).hexdigest()
    build = json.loads(build_path.read_text()) | {"outputs": outputs, "build_sha256": identity, "ec": {"ec_sha256": sha, "ec_version": "1.0"} if block else None}
    build_path.write_text(json.dumps(build))
    review.write_text(f"Build-SHA256: {identity}\n" + review.read_text().split("\n", 1)[1])
    if tree_:
        (w[1] / "ec/s-a").mkdir(parents=True)
        (w[1] / "ec/s-a/EC-APPLY.json").write_text(json.dumps({"deepened_cells": deepened}))
    sources = [{"source_id": "s-a", "status": "FIX", "counts": {"filled-hole": 3, "filled-pit": 1, "verified": 5, "unresolved-hole": 7}},
               {"source_id": "s-r", "status": "REFUSED", "counts": {"filled-hole": 50, "verified": 50}}]
    asks = ["second-survey:s-a:7", "refused:s-r:sign-positive"]
    (w[1] / "EC.json").write_text(json.dumps({"ec_version": "1.0", "ec_sha256": EC_SHA, "sources": sources, "operator_asks": asks}))
    (w[1] / "INTAKE.csv").write_text(f"source_id,use\ns-a,publish\ns-r,{use}\n")
    calls, before, inner = [], tree(w[0]), runner()

    def run(cmd, cwd=None, env=None):
        if cmd[1] == str(rp.CORRECT):
            calls.append(cmd[2:])
            return SimpleNamespace(returncode=check[0], stdout=check[1])
        return inner(cmd, cwd, env)
    code = rp.main([str(w[1]), "--repo", str(w[0]), "--ledger", str(w[2])], run=run,
                   loader=lambda root, rid: ({"id": rid, "name": "Syn Bay", "status": "preview"}, SRC))
    return w, code, calls, before


def test_ec_run_passes_rule_six_with_counts_and_a_run_without_ec_is_byte_identical(tmp_path):
    w, code, calls, _ = ec_world(tmp_path / "ec")
    text = (w[1] / "PUBLISH.md").read_text()
    assert code == 0 and calls == [["--check", str(w[1].resolve())]] and ",publish,reviewed,none," in w[2].read_text()
    assert "\nError correction: 1 sources corrected, 4 filled cells, 5 verified cells, 2 unresolved blocks (EC 1.0)\nReviewer: " in text
    plain = world(tmp_path / "plain")
    build_path = plain[1] / "BUILD.json"
    build_path.write_text(json.dumps(json.loads(build_path.read_text()) | {"ec": None}))
    assert publish(plain) == 0 and hashlib.sha256((plain[1] / "PUBLISH.md").read_bytes()).hexdigest() == FROZEN
    skill = (ROOT / "skills/skippercast-region-process/SKILL.md").read_text()
    assert len(skill.splitlines()) <= 70 and "2a. Correct: `python3 skills/skippercast-region-correct/scripts/region_correct.py" in skill
    assert all(word in skill for word in ("`correct`", "ec-refused:<id>", "ec-receipt-invalid", "ec-deepened:<id>", "EC receipts (`--check`)"))


@pytest.mark.parametrize("kwargs,reason,then", [
    ({"block": False}, "ec-receipt-invalid", rp.NEXT["ec"]), ({"tree_": False}, "ec-receipt-invalid", rp.NEXT["ec"]),
    ({"check": (1, "EC OK 2 rows\n")}, "ec-receipt-invalid", rp.NEXT["ec"]), ({"check": (0, "EC OK 2 rows, stale\n")}, "ec-receipt-invalid", rp.NEXT["ec"]),
    ({"sha": "f" * 64}, "ec-receipt-invalid", rp.NEXT["ec"]), ({"deepened": 1}, "ec-deepened:s-a", rp.NEXT["ec"]),
    ({"deepened": False}, "ec-deepened:s-a", rp.NEXT["ec"]),
    ({"output": False}, "no-publishable-output", "ec-refused:s-r:sign-positive ("),
    ({"output": False, "use": "held"}, "no-publishable-output", "see BUILD.json not_built")])
def test_ec_rule_six_holds_with_its_reason_and_leaves_the_repo_untouched(tmp_path, kwargs, reason, then):
    w, code, _, before = ec_world(tmp_path, **kwargs)
    text = (w[1] / "PUBLISH.md").read_text()
    assert code == 1 and tree(w[0]) == before and f"HELD: {reason}\n" in text and f"\nNext: {then}" in text
    identity = json.loads((w[1] / "BUILD.json").read_text())["build_sha256"]
    assert w[2].read_text() == ROWS.replace(OLD, f"syn-bay,review,held,{reason},run-20261105,{identity},PASS,gpt-test,,")
