"""C1–C3: exercise the preview planner against a disposable checkout."""

from hashlib import sha256
import json
import os
import subprocess
import sys

import pytest

from tests._support import ROOT

CLI = ROOT / "scripts/relief/style_preview_plan.py"
WINDOW = dict(id="inlet", center=[-121.5, 35.25], size_m=2000, zoom=13)
SECOND = dict(id="outer", center=[-122, 35], size_m=6000, zoom=11)


def _write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


@pytest.fixture
def repo(tmp_path):
    # Both styles resolve when active; retire the legacy style
    # for refusal cases without introducing a third style.
    def build(*, retired=False, default="deep-fixed-v1"):
        _write(tmp_path / "style/next.json", {"ink": "blue"})
        _write(tmp_path / "style/groups.json", {"ink": "paint"})
        empty = sha256(b"{}").hexdigest()
        _write(tmp_path / "style/index.json", {
            "default": default,
            "versions": {
                "deep-fixed-v1": {"legacy": True, "status": "retired" if retired else "active"},
                "next": {"status": "active", "file": "next.json",
                         "sha256": sha256(b'{"ink": "blue"}').hexdigest(),
                         "digests": dict(baked=empty, contours=empty, habitat=empty,
                                         paint=sha256(b'{"ink":"blue"}').hexdigest())},
            },
        })
        schema = tmp_path / "schemas/sc-render-v1.schema.json"
        schema.parent.mkdir()
        schema.write_bytes((ROOT / "schemas" / schema.name).read_bytes())
        regions = {"defaulted": {}, "pinned": {"style": "deep-fixed-v1"}, "already": {"style": "next"}}
        _write(tmp_path / "dist/regions/index.json", {"regions": [{"id": region} for region in regions]})
        for region, pin in regions.items():
            _write(tmp_path / "regions" / region / "render.json", {
                "schema": "sc-render/1", "region": region, "piers": [],
                "previews": [WINDOW, SECOND] if region == "defaulted" else [SECOND], **pin,
            })
        return tmp_path

    return build


def _run(root, *args, explicit_root=True):
    env = dict(os.environ, SKIPPERCAST_ROOT="wrong-checkout" if explicit_root else str(root))
    root_args = ["--root", str(root)] if explicit_root else []
    result = subprocess.run([sys.executable, "-B", str(CLI), *args, *root_args],
                            cwd=root, env=env, capture_output=True, text=True, check=False)
    return result.returncode, result.stderr, result.stdout


def test_c1_all_regions_and_window_rows(repo):
    """C1: ignoring the index or dropping the second window gives an incomplete plan."""
    assert _run(repo(), "next") == (0, "",
        "defaulted: current=deep-fixed-v1\n"
        "  inlet center=[-121.5, 35.25] size_m=2000 zoom=13\n"
        "  outer center=[-122, 35] size_m=6000 zoom=11\n"
        "pinned: current=deep-fixed-v1\n"
        "  outer center=[-122, 35] size_m=6000 zoom=11\n"
        "already: current=next unchanged (already on next)\n"
        "regions=3 windows=3 unchanged=1 invalid=0\n")


def test_c1_subset_and_legacy_candidate(repo):
    """C1: a valid legacy candidate needs no tokens, and a pin overrides the default."""
    code, stderr, stdout = _run(repo(default="next"), "deep-fixed-v1", "already", "pinned", "--json",
                                explicit_root=False)
    assert (code, stderr, json.loads(stdout)) == (0, "", {
        "version": "deep-fixed-v1",
        "regions": [
            dict(region="already", current="next", status="preview", windows=[SECOND]),
            dict(region="pinned", current="deep-fixed-v1", status="unchanged", windows=[]),
        ],
        "summary": dict(regions=2, windows=1, unchanged=1, invalid=0),
    })


@pytest.mark.parametrize("version", [
    pytest.param("deep-fixed-v1", id="C1: retired candidate refuses before planning"),
    pytest.param("absent", id="C1: unknown candidate refuses before planning"),
])
def test_c1_unavailable_candidates(repo, version):
    """C1: reporting on a retired or absent version would advertise an unusable rollout."""
    assert _run(repo(retired=True, default="next"), version, "--json") == (
        1, f"style_preview_plan.py: unavailable render style: {version}\n", "")


def test_c1_unindexed_region_refused(repo):
    """C1: an explicit selector must not invent a region outside the release index."""
    assert _run(repo(), "next", "unlisted") == (1, "style_preview_plan.py: unknown region: unlisted\n", "")


def test_c1_candidate_tokens_verified(repo):
    """C1: merely reading an active index entry would miss a corrupt token file."""
    root = repo()
    path = root / "style/next.json"
    expected = sha256(path.read_bytes()).hexdigest()
    raw = b'{"ink": "red"}'
    path.write_bytes(raw)
    assert _run(root, "next", "defaulted") == (1,
        "style_preview_plan.py: next: sha256 mismatch "
        f"(expected {expected}, got {sha256(raw).hexdigest()})\n", "")


def test_c2_default_match_is_not_a_pin(repo):
    """C2: comparing resolved versions alone would suppress an unpinned region's windows."""
    assert _run(repo(default="next"), "next", "defaulted", "already") == (0, "",
        "defaulted: current=next\n"
        "  inlet center=[-121.5, 35.25] size_m=2000 zoom=13\n"
        "  outer center=[-122, 35] size_m=6000 zoom=11\n"
        "already: current=next unchanged (already on next)\n"
        "regions=2 windows=2 unchanged=1 invalid=0\n")


def test_c2_broken_config_does_not_stop_remaining_regions(repo):
    """C2: a broken render recipe must not hide a later region or exit successfully."""
    root = repo()
    (root / "regions/pinned/render.json").write_text("{", encoding="utf-8")
    assert _run(root, "next", "pinned", "defaulted", "already") == (1, "",
        "pinned: current=unknown invalid: Expecting property name enclosed in double quotes: "
        "line 1 column 2 (char 1)\n"
        "defaulted: current=deep-fixed-v1\n"
        "  inlet center=[-121.5, 35.25] size_m=2000 zoom=13\n"
        "  outer center=[-122, 35] size_m=6000 zoom=11\n"
        "already: current=next unchanged (already on next)\n"
        "regions=3 windows=2 unchanged=1 invalid=1\n")


def test_c3_no_outputs_created_or_inputs_rewritten(repo):
    """C3: a planning run must not create output or even rewrite the same config bytes."""
    root = repo(retired=True, default="next")

    def snapshot():
        return {path.relative_to(root): (path.read_bytes(), path.stat().st_mtime_ns)
                if path.is_file() else None for path in root.rglob("*")}

    before = snapshot()
    code, stderr, stdout = _run(root, "next", "--json")
    assert (code, stderr, json.loads(stdout)) == (1, "", {
        "version": "next",
        "regions": [
            dict(region="defaulted", current="next", status="preview", windows=[WINDOW, SECOND]),
            dict(region="pinned", current=None, status="invalid", windows=[],
                 error="unavailable render style: deep-fixed-v1"),
            dict(region="already", current="next", status="unchanged", windows=[]),
        ],
        "summary": dict(regions=3, windows=2, unchanged=1, invalid=1),
    })
    assert snapshot() == before
