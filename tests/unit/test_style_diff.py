"""C0–C2: reviewer-facing style diff, tested through the CLI on a synthetic root."""

from hashlib import sha256
import json
import subprocess
import sys
from typing import Any

import pytest

from scripts.relief import style_diff
from skippercast import style
from tests._support import ROOT

CLI = ROOT / "scripts/relief/style_diff.py"


def _sha(value):
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return sha256(raw).hexdigest()


@pytest.fixture
def styles(tmp_path):
    # Explicit subsets keep the oracle independent of the CLI's grouping logic.
    def write(versions):
        (tmp_path / "groups.json").write_text(json.dumps({
            "colors": "paint", "colors.mix": "baked", "tiers": "contours",
            "labels": "habitat", "note": "meta", "retired": "meta",
        }))
        entries: dict[str, dict[str, Any]] = {"legacy": {"legacy": True}}
        for name, tokens, subsets in versions:
            raw = json.dumps(tokens).encode()
            file = f"{name}.json"
            (tmp_path / file).write_bytes(raw)
            entries[name] = {"file": file, "sha256": sha256(raw).hexdigest(), "digests": {
                group: _sha(subsets.get(group, {})) for group in ("baked", "contours", "habitat", "paint")
            }}
        (tmp_path / "index.json").write_text(json.dumps({"default": "a", "versions": entries}))
        return tmp_path

    return write


@pytest.fixture
def mixed(styles):
    return styles([
        ("a", {"colors": {"ink": "gray", "mix": [1, 2]}}, {
            "baked": {"colors": {"mix": [1, 2]}}, "paint": {"colors": {"ink": "gray"}},
        }),
        ("b", {"colors": {"ink": "blue", "mix": [1, 3]}}, {
            "baked": {"colors": {"mix": [1, 3]}}, "paint": {"colors": {"ink": "blue"}},
        }),
    ])


def _run(root, *args):
    return subprocess.run([sys.executable, str(CLI), *args, "--root", str(root)],
                          capture_output=True, text=True, check=False)


def test_c1_mixed_json(mixed):
    """C1: a broad paint rule must not swallow the nested baked leaf or hide its digest."""
    result = _run(mixed, "a", "b", "--json")
    assert (result.returncode, result.stderr, json.loads(result.stdout)) == (0, "", {
        "changes": {
            "baked": [{"path": "colors.mix", "old": [1, 2], "new": [1, 3]}],
            "paint": [{"path": "colors.ink", "old": "gray", "new": "blue"}],
        },
        "digests": {
            "baked": {"old": _sha({"colors": {"mix": [1, 2]}}), "new": _sha({"colors": {"mix": [1, 3]}})},
            "paint": {"old": _sha({"colors": {"ink": "gray"}}), "new": _sha({"colors": {"ink": "blue"}})},
        },
        "groups_changed": ["baked", "paint"], "paint_only": False,
    })


def test_c1_text_meta_add_remove(styles):
    """C1: the text report must distinguish a null value from an absent metadata key."""
    root = styles([("a", {"retired": None}, {}), ("b", {"note": None}, {})])
    result = _run(root, "a", "b")
    assert (result.returncode, result.stderr, result.stdout) == (0, "",
        '[meta]\n  note: <absent> -> null\n  retired: null -> <absent>\n'
        'groups_changed=["meta"] paint_only=true\n')


def test_c1_text_digest(mixed):
    """C1: omitting --json must still show changes and digests in old-to-new order."""
    result = _run(mixed, "b", "a")
    assert (result.returncode, result.stderr, result.stdout) == (0, "",
        '[baked]\n  colors.mix: [1,3] -> [1,2]\n'
        f'  digest: {_sha({"colors": {"mix": [1, 3]}})} -> {_sha({"colors": {"mix": [1, 2]}})}\n'
        '[paint]\n  colors.ink: "blue" -> "gray"\n'
        f'  digest: {_sha({"colors": {"ink": "blue"}})} -> {_sha({"colors": {"ink": "gray"}})}\n'
        'groups_changed=["baked","paint"] paint_only=false\n')


@pytest.mark.parametrize(("group", "key", "paint_only"), [
    pytest.param("paint", "colors", True, id="C2: paint alone needs no rebuild"),
    pytest.param("contours", "tiers", False, id="C2: contours alone requires rebuild"),
    pytest.param("habitat", "labels", False, id="C2: habitat alone requires rebuild"),
])
def test_c2_single_group(styles, group, key, paint_only):
    """C2: exercising each group alone catches omitted rebuild groups and Python bool/int equality."""
    old, new = {key: True}, {key: 1}
    root = styles([("a", old, {group: old}), ("b", new, {group: new})])
    result = _run(root, "a", "b", "--json")
    assert (result.returncode, result.stderr, json.loads(result.stdout)) == (0, "", {
        "changes": {group: [{"path": key, "old": True, "new": 1}]},
        "digests": {group: {"old": _sha(old), "new": _sha(new)}},
        "groups_changed": [group], "paint_only": paint_only,
    })


def test_c2_identical(mixed):
    """C2: an identical comparison must not invent changes or require a rebuild."""
    result = _run(mixed, "a", "a", "--json")
    assert (result.returncode, result.stderr, json.loads(result.stdout)) == (0, "", {
        "changes": {}, "digests": {}, "groups_changed": [], "paint_only": True,
    })


@pytest.mark.parametrize(("a", "b"), [("unknown", "b"), ("a", "unknown")])
def test_c2_unknown_version(mixed, a, b):
    """C2: either missing ID must produce usage status, not a traceback or report."""
    result = _run(mixed, a, b, "--json")
    assert (result.returncode, result.stdout, result.stderr.splitlines()[-1]) == (
        2, "", "style_diff.py: error: unknown style version: unknown",
    )


@pytest.mark.parametrize("version", ["a", "b"])
@pytest.mark.parametrize("field", ["sha256", "digests"])
def test_c2_refuses_unverified_version(mixed, version, field):
    """C2: checking only one snapshot or only its file SHA would miss changed index evidence."""
    path = mixed / "index.json"
    index = json.loads(path.read_bytes())
    entry = index["versions"][version]
    expected = "0" * 64
    if field == "sha256":
        actual = entry["sha256"]
        entry["sha256"] = expected
        error = f"sha256 mismatch (expected {expected}, got {actual})"
    else:
        entry["digests"]["baked"] = expected
        error = "groups.json disagrees with the index digests (regenerate with scripts/style/gen_style.py)"
    path.write_text(json.dumps(index))
    result = _run(mixed, "a", "b", "--json")
    assert (result.returncode, result.stdout, result.stderr) == (1, "", f"style_diff.py: {version}: {error}\n")


def test_c2_refuses_legacy(mixed):
    """C2: known legacy entries must honor the loader's refusal, not look like unknown IDs."""
    result = _run(mixed, "a", "legacy", "--json")
    assert (result.returncode, result.stdout, result.stderr) == (
        1, "", "style_diff.py: legacy: legacy style; use the legacy builder\n",
    )


@pytest.mark.parametrize("helper", ["_verified_tokens", "_leaf_groups"])
def test_c0_uses_loader_helpers_after_public_load(mixed, monkeypatch, helper):
    """C0: replacing a helper in the diff with local logic must fail even if load still uses it."""
    original = getattr(style, helper)
    load = style.load
    verified = []

    class HelperRefusal(RuntimeError):
        pass

    def record_load(version, root):
        snapshot = load(version, root)
        verified.append((version, root))
        return snapshot

    def probe(*args):
        if len(verified) == 2:
            raise HelperRefusal(helper)
        return original(*args)

    monkeypatch.setattr(style, "load", record_load)
    monkeypatch.setattr(style, helper, probe)
    with pytest.raises(HelperRefusal) as caught:
        style_diff.main(["a", "b", "--root", str(mixed), "--json"])
    assert type(caught.value) is HelperRefusal
    assert caught.value.args == (helper,)
    assert verified == [("a", mixed), ("b", mixed)]
