import hashlib
import json
from pathlib import Path

import pytest

from skippercast.coastal import child_release as cr
from tests.unit.child_release_fixture import fixture

DUPLICATE = "duplicate metadata member"
ROLES = ("render", "browser")
CONTRACT = "coastal-test-document-v1"
GLOBAL = "coastal-mission-global-clock-v1"


@pytest.fixture(autouse=True)
def frozen_clocks(monkeypatch):
    monkeypatch.setattr(cr.time, "time", lambda: 1_800_000_000.0)
    monkeypatch.setattr(cr.time, "monotonic", lambda: 50_000.0)


def _snapshot(root):
    return {str(p): p.read_bytes() for p in sorted(Path(root).rglob("*")) if p.is_file()}


def _wrap(root, name, data, contract=CONTRACT):
    (root / name).write_bytes(data)
    return dict(root=str(root), path=name, bytes=len(data),
                sha256=hashlib.sha256(data).hexdigest(), contract=contract)


def _read(root, name, text):
    return cr._document(_wrap(root, name, text.encode()), root, CONTRACT)


def _rewrite(ctx, key, old, new):
    """Replace one text span in a pinned document and rebind its descriptor."""
    ref = ctx[key]
    path = Path(ref["root"]) / ref["path"]
    text = path.read_text()
    assert text.count(old) == 1
    ctx[key] = _wrap(Path(ref["root"]), ref["path"], text.replace(old, new).encode(), ref["contract"])


@pytest.mark.parametrize("second", [CONTRACT, "other"])
def test_duplicate_root_member_refuses_after_descriptor_authentication(tmp_path, second):
    text = '{"schema":"%s","schema":"%s"}' % (CONTRACT, second)
    with pytest.raises(ValueError, match=DUPLICATE):
        _read(tmp_path, "d.json", text)
    # a stale hash still fails at the earlier descriptor gate
    wrapper = _wrap(tmp_path, "d.json", text.encode())
    wrapper["sha256"] = "0" * 64
    with pytest.raises(ValueError, match="metadata changed or digest mismatch"):
        cr._document(wrapper, tmp_path, CONTRACT)


def test_escaped_equivalent_names_collide(tmp_path):
    with pytest.raises(ValueError, match=DUPLICATE):
        _read(tmp_path, "e.json", '{"schema":"%s","schem\\u0061":"%s"}' % (CONTRACT, CONTRACT))
    # distinct case-sensitive names stay distinct
    doc = _read(tmp_path, "c.json", '{"schema":"%s","Schema":1,"SCHEMA":2}' % CONTRACT)
    assert doc == {"schema": CONTRACT, "Schema": 1, "SCHEMA": 2}


def test_nested_and_array_object_duplicates_refuse(tmp_path):
    with pytest.raises(ValueError, match=DUPLICATE):
        _read(tmp_path, "n.json", '{"schema":"%s","a":{"b":{"k":1,"k":2}}}' % CONTRACT)
    with pytest.raises(ValueError, match=DUPLICATE):
        _read(tmp_path, "a.json", '{"schema":"%s","a":[{"ok":1},{"k":1,"k":1}]}' % CONTRACT)
    # malformed non-duplicate JSON keeps its decode error
    with pytest.raises(json.JSONDecodeError):
        _read(tmp_path, "m.json", '{"schema":')
    # unique-key values are preserved
    good = _read(tmp_path, "g.json", '{"schema":"%s","a":[{"k":1},{"k":2}],"b":{"k":3}}' % CONTRACT)
    assert good["a"] == [{"k": 1}, {"k": 2}] and good["b"] == {"k": 3}


def test_duplicate_diagnostic_does_not_echo_document(tmp_path):
    with pytest.raises(ValueError) as caught:
        _read(tmp_path, "s.json", '{"schema":"%s","secret-name":"secret-value","secret-name":"x"}' % CONTRACT)
    assert str(caught.value) == DUPLICATE


CASES = {
    "duplicate_schema": ("global_clock", '{"', '{"schema":"wrong","'),
    "duplicate_stop": ("mapping_stop", '"descendants_empty":true',
                       '"descendants_empty":false,"descendants_empty":true'),
    "escaped_duplicate": ("global_clock", '"schema":"%s"' % GLOBAL,
                          '"schem\\u0061":"wrong","schema":"%s"' % GLOBAL),
    "nested_duplicate": ("mapping_stop", '"ActiveState":"inactive"',
                         '"ActiveState":"active","ActiveState":"inactive"'),
}


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("case", sorted(CASES))
def test_public_release_rejects_ambiguous_clocks_and_stop(tmp_path, role, case):
    ctx, now, _ = fixture(tmp_path, role)
    key, old, new = CASES[case]
    ref = ctx[key]
    text = (Path(ref["root"]) / ref["path"]).read_text()
    if case == "duplicate_schema":
        ctx[key] = _wrap(Path(ref["root"]), ref["path"], (new + text[len(old):]).encode(), ref["contract"])
    else:
        _rewrite(ctx, key, old, new)
    before = _snapshot(tmp_path)
    with pytest.raises(ValueError, match=DUPLICATE):
        cr.validate_child_release(ctx, role, now, now + 60)
    assert not Path(ctx["output_root"]).exists()
    assert _snapshot(tmp_path) == before


@pytest.mark.parametrize("role", ROLES)
def test_unique_key_release_control_unchanged(tmp_path, role):
    ctx, now, _ = fixture(tmp_path, role)
    before = _snapshot(tmp_path)
    out = cr.validate_child_release(ctx, role, now, now + 60)
    assert out["output_root"] == ctx["output_root"]
    assert out["mapping_stop"]["properties"] == {"ActiveState": "inactive", "ControlGroup": ""}
    assert out["global_clock"]["schema"] == GLOBAL
    assert _snapshot(tmp_path) == before
    assert not Path(ctx["output_root"]).exists()


def test_opaque_raw_control_is_not_json_parsed(tmp_path):
    for name, data in (("raw.bin", b"\x00not json"), ("dup.json", b'{"a":1,"a":2}')):
        wrapper = _wrap(tmp_path, name, data)
        assert cr._document(wrapper, tmp_path, CONTRACT, raw=True) == data
        with pytest.raises(ValueError):
            cr._document(wrapper, tmp_path, CONTRACT)
