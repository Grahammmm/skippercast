"""Engineering resource roots: ancestor aliases refuse before inventory or receipt writes."""
import hashlib
import os

import pytest

from skippercast.coastal import cached_inventory as ci

ALIAS = "resource root alias"


def tree(base):
    """Real retained/scratch directories under base with a sentinel in retained."""
    real = base / "real"
    (real / "retained").mkdir(parents=True)
    (real / "scratch").mkdir()
    (real / "retained" / "sentinel.bin").write_bytes(b"keep")
    return real


def snapshot(real):
    return sorted((str(p.relative_to(real)), p.read_bytes() if p.is_file() else None) for p in real.rglob("*"))


def test_retained_ancestor_alias_refuses_before_receipt(tmp_path):
    real = tree(tmp_path)
    (tmp_path / "alias").symlink_to(real)
    before = snapshot(real)
    with pytest.raises(ValueError, match=ALIAS):
        ci.resource_inventory(tmp_path / "alias" / "retained", real / "scratch")
    with pytest.raises(ValueError, match=ALIAS):
        ci.write_engineering_receipt(tmp_path / "alias" / "retained", real / "scratch", "r.json", {"a": 1})
    assert not (real / "retained" / "r.json").exists()
    assert snapshot(real) == before
    assert os.readlink(tmp_path / "alias") == str(real)


def test_scratch_ancestor_alias_blocks_valid_retained_write(tmp_path):
    real = tree(tmp_path)
    (tmp_path / "alias").symlink_to(real)
    with pytest.raises(ValueError, match=ALIAS):
        ci.resource_inventory(real / "retained", tmp_path / "alias" / "scratch")
    with pytest.raises(ValueError, match=ALIAS):
        ci.write_engineering_receipt(real / "retained", tmp_path / "alias" / "scratch", "r.json", {"a": 1})
    assert not (real / "retained" / "r.json").exists()


def test_deep_relative_and_final_root_aliases_refuse(tmp_path, monkeypatch):
    real = tree(tmp_path)
    deep = tmp_path / "x" / "y"
    deep.mkdir(parents=True)
    (deep / "link").symlink_to(real)
    with pytest.raises(ValueError, match=ALIAS):
        ci.resource_inventory(tmp_path / "x" / "y" / "link" / "retained", real / "scratch")
    (tmp_path / "top").symlink_to(tmp_path / "x")
    with pytest.raises(ValueError, match=ALIAS):
        ci.resource_inventory(tmp_path / "top" / "y" / "link" / "retained", real / "scratch")
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ValueError, match=ALIAS):
        ci.resource_inventory("x/y/link/retained", "real/scratch")
    with pytest.raises(ValueError, match=ALIAS):
        ci.resource_inventory("real/retained", "top/y")
    (tmp_path / "final").symlink_to(real / "retained")
    with pytest.raises(ValueError, match=ALIAS):
        ci.resource_inventory("final", "real/scratch")
    assert os.readlink(deep / "link") == str(real)
    assert os.readlink(tmp_path / "final") == str(real / "retained")


def test_absent_leaf_below_alias_is_not_zero_inventory(tmp_path):
    real = tree(tmp_path)
    (tmp_path / "alias").symlink_to(real)
    before = snapshot(real)
    with pytest.raises(ValueError, match=ALIAS):
        ci.resource_inventory(tmp_path / "alias" / "absent", real / "scratch")
    with pytest.raises(ValueError, match=ALIAS):
        ci.resource_inventory(real / "retained", tmp_path / "alias" / "absent")
    assert snapshot(real) == before


def test_ordinary_roots_keep_exact_counts_and_receipt_bytes(tmp_path):
    real = tree(tmp_path)
    (real / "retained" / "nested").mkdir()
    (real / "retained" / "nested" / "b.bin").write_bytes(b"12345")
    (real / "scratch" / "s.bin").write_bytes(b"abc")
    inventory = ci.resource_inventory(real / "retained", real / "scratch")
    assert inventory["retained"] == dict(root=str(real / "retained"), regular_bytes=9, regular_files=2,
                                         symlinks_preserved_not_followed=0, cap_bytes=524288)
    assert inventory["scratch"] == dict(root=str(real / "scratch"), regular_bytes=3, regular_files=1,
                                        symlinks_preserved_not_followed=0, cap_bytes=268435456)
    value = {"k": [1, 2]}
    result = ci.write_engineering_receipt(real / "retained", real / "scratch", "r.json", value)
    payload = ci.encoded(value)
    assert (real / "retained" / "r.json").read_bytes() == payload
    assert result == dict(path=str(real / "retained" / "r.json"), bytes=len(payload),
                          sha256=hashlib.sha256(payload).hexdigest())
    with pytest.raises(ValueError, match="preserve existing engineering receipt"):
        ci.write_engineering_receipt(real / "retained", real / "scratch", "r.json", {"other": 1})
    assert (real / "retained" / "r.json").read_bytes() == payload


def test_descendant_links_are_preserved_and_not_followed(tmp_path):
    real = tree(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "big.bin").write_bytes(b"x" * 1000)
    (real / "retained" / "file-link").symlink_to(outside / "big.bin")
    (real / "retained" / "dir-link").symlink_to(outside)
    (real / "retained" / "broken").symlink_to(tmp_path / "missing")
    inventory = ci.resource_inventory(real / "retained", real / "scratch")
    assert inventory["retained"]["symlinks_preserved_not_followed"] == 3
    assert inventory["retained"]["regular_bytes"] == 4
    assert inventory["retained"]["regular_files"] == 1
    result = ci.write_engineering_receipt(real / "retained", real / "scratch", "r.json", {"a": 1})
    assert (real / "retained" / "r.json").read_bytes() == ci.encoded({"a": 1})
    assert result["bytes"] == len(ci.encoded({"a": 1}))


def test_unaliased_missing_roots_keep_zero_report(tmp_path):
    inventory = ci.resource_inventory(tmp_path / "none-a", tmp_path / "none-b")
    for role in ("retained", "scratch"):
        assert inventory[role]["regular_bytes"] == inventory[role]["regular_files"] == 0
        assert inventory[role]["symlinks_preserved_not_followed"] == 0
    assert not (tmp_path / "none-a").exists()
    (tmp_path / "empty").mkdir()
    assert ci.resource_inventory(tmp_path / "empty", tmp_path / "none-b")["retained"]["regular_files"] == 0


def test_caps_and_occupied_receipt_entries_refuse_unchanged(tmp_path):
    real = tree(tmp_path)
    (real / "retained" / "full.bin").write_bytes(b"x" * 524288)
    with pytest.raises(ValueError, match="retained engineering allowance exceeded"):
        ci.resource_inventory(real / "retained", real / "scratch")
    (real / "retained" / "full.bin").write_bytes(b"x" * 524284)
    assert ci.resource_inventory(real / "retained", real / "scratch")["retained"]["regular_bytes"] == 524288
    (real / "retained" / "full.bin").unlink()
    (real / "retained" / "dangling.json").symlink_to(tmp_path / "nowhere")
    with pytest.raises(ValueError, match="preserve existing engineering receipt"):
        ci.write_engineering_receipt(real / "retained", real / "scratch", "dangling.json", {"a": 1})
    assert not (tmp_path / "nowhere").exists()
    (real / "retained" / "taken.json").write_bytes(b"old")
    with pytest.raises(ValueError, match="preserve existing engineering receipt"):
        ci.write_engineering_receipt(real / "retained", real / "scratch", "taken.json", {"a": 1})
    assert (real / "retained" / "taken.json").read_bytes() == b"old"
