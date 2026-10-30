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

def runner(drift=False):
    """Stands in for region_review.py --check and platform.build (dist = copy of the catalog file); `drift` changes the 2nd build."""
    builds = []

    def run(cmd, cwd=None, env=None):
        if cmd[1].endswith("region_review.py"):
            return SimpleNamespace(returncode=0, stdout="REVIEW OK syn-bay PASS\n")
        assert env["PYTHONPATH"] == str(cwd / "src") and cmd[2:] == ["skippercast.platform.build"]
        builds.append(1)
        (cwd / "dist/regions/syn-bay/depth-contours.geojson").write_bytes((cwd / "catalog/depth-contours/syn-bay.geojson").read_bytes() + (b"x" if drift and len(builds) == 2 else b""))
        return SimpleNamespace(returncode=0, stdout="")
    return run

def publish(w, status="preview", drift=False):
    return rp.main([str(w[1]), "--repo", str(w[0]), "--ledger", str(w[2])], run=runner(drift), loader=lambda root, rid: ({"id": rid, "name": "Syn Bay", "status": status}, SRC))

def test_approved_cross_family_run_publishes_and_repeats_byte_for_byte(tmp_path):
    a, b = world(tmp_path / "a"), world(tmp_path / "b")
    assert publish(a) == 0 and publish(b) == 0
    text = (a[1] / "PUBLISH.md").read_text()
    assert (a[0] / "catalog/depth-contours/syn-bay.geojson").read_bytes() == (a[1] / "candidate/syn-bay.geojson").read_bytes()
    assert "## PR body" in text and "## CHANGELOG line" in text and "phone capture not visually inspected" in text and "Not for navigation" in text
    identity = json.loads((a[1] / "BUILD.json").read_text())["build_sha256"]
    assert a[2].read_text() == ROWS.replace(OLD, "syn-bay,publish,reviewed,none,run-20261105," + identity + ",PASS (visual not inspected),gpt-test,,")
    assert tree(a[0]) == tree(b[0]) and text == (b[1] / "PUBLISH.md").read_text() and a[2].read_bytes() == b[2].read_bytes()

@pytest.mark.parametrize("kwargs,status,drift,reason", [({"source": "s-c"}, "preview", False, "source-candidate:s-c"), ({}, "draft", False, "region-draft"),
                                                          ({"family": " ANTHROPIC "}, "preview", False, "review-family"), ({"sha": "c" * 64}, "preview", False, "review-sha-mismatch"),
                                                          ({"stamp": True}, "preview", False, "publication-held"), ({}, "preview", True, "build-not-reproducible")])
def test_each_failed_rule_holds_with_its_reason_and_leaves_the_repo_untouched(tmp_path, kwargs, status, drift, reason):
    w = world(tmp_path, **kwargs)
    before = tree(w[0])
    assert publish(w, status, drift) == 1
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
