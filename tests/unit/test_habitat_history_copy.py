import errno
import hashlib
import os
from pathlib import Path

import pytest

from skippercast.pipeline.habitat_history_copy import copy_previous_history


def _ref(prior: Path, label: str, data: bytes) -> dict:
    sha = hashlib.sha256(data).hexdigest()
    name = f"habitat-history/{label}-{sha[:16]}.json"
    source = prior / name
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(data)
    return {"path": name, "bytes": len(data), "sha256": sha}


def test_c1_carries_two_days_in_first_seen_order(tmp_path):
    # Iterating only one day, sorting paths or returning a shared tile twice loses the contract.
    prior, target = tmp_path / "prior", tmp_path / "target"
    first = _ref(prior, "z-1", b"{}")
    shared = _ref(prior, "a-2", b"[]")
    last = _ref(prior, "m-3", b"null")
    history = [
        {"sample_at": "2026-11-19T00:00:00Z", "tiles": [first, shared]},
        {"sample_at": "2026-11-18T00:00:00Z", "tiles": [shared, last]},
    ]

    assert copy_previous_history(history, prior, target) == [first["path"], shared["path"], last["path"]]
    assert {p.relative_to(target).as_posix(): p.read_bytes() for p in target.rglob("*.json")} == {
        first["path"]: b"{}", shared["path"]: b"[]", last["path"]: b"null",
    }


def test_c1_empty_history_leaves_target_absent(tmp_path):
    # Eager creation would leave a history directory even with no references.
    target = tmp_path / "target"
    assert copy_previous_history([], tmp_path / "prior", target) == []
    assert not target.exists()


def test_c2_bad_path_in_later_day_refuses_before_copying(tmp_path):
    # Validating during the copy loop would leave the first day's tile behind.
    prior, target = tmp_path / "prior", tmp_path / "target"
    good = _ref(prior, "first", b"{}")
    bad = {**good, "path": good["path"].replace("habitat-history/", "habitat-history/../")}

    with pytest.raises(ValueError) as error:
        copy_previous_history([{"tiles": [good]}, {"tiles": [bad]}], prior, target)
    assert (type(error.value), str(error.value)) == (ValueError, "path")
    assert not target.exists()


def test_c2_missing_file_preserves_earlier_copy(tmp_path):
    # A missing source must not be silently skipped or roll back the earlier write.
    prior, target = tmp_path / "prior", tmp_path / "target"
    good = _ref(prior, "first", b"{}")
    missing = {**good, "path": good["path"].replace("/first-", "/missing-")}

    with pytest.raises(FileNotFoundError) as error:
        copy_previous_history([{"tiles": [good, missing]}], prior, target)
    expected = FileNotFoundError(errno.ENOENT, os.strerror(errno.ENOENT), str(prior / missing["path"]))
    assert (type(error.value), str(error.value)) == (FileNotFoundError, str(expected))
    assert (target / good["path"]).read_bytes() == b"{}"
    assert not (target / missing["path"]).exists()


@pytest.mark.parametrize(("field", "wrong"), [("bytes", 3), ("sha256", "0" * 64)])
def test_c2_checks_both_integrity_fields_before_overwriting(tmp_path, field, wrong):
    # Checking just length or just digest lets one of these bad refs replace an existing file.
    prior, target = tmp_path / "prior", tmp_path / "target"
    good = _ref(prior, "first", b"{}")
    bad = {**_ref(prior, "second", b"[]"), field: wrong}
    dest = target / bad["path"]
    dest.parent.mkdir(parents=True)
    dest.write_bytes(b"null")

    with pytest.raises(ValueError) as error:
        copy_previous_history([{"tiles": [good, bad]}], prior, target)
    assert (type(error.value), str(error.value)) == (ValueError, "integrity")
    assert (target / good["path"]).read_bytes() == b"{}"
    assert dest.read_bytes() == b"null"


def test_c2_checks_integrity_even_for_a_repeated_path(tmp_path):
    # Deduplicating before verification would let the second day's bad digest through.
    prior, target = tmp_path / "prior", tmp_path / "target"
    good = _ref(prior, "shared", b"{}")
    bad = {**good, "sha256": "0" * 64}

    with pytest.raises(ValueError) as error:
        copy_previous_history([{"tiles": [good]}, {"tiles": [bad]}], prior, target)
    assert (type(error.value), str(error.value)) == (ValueError, "integrity")
    assert (target / good["path"]).read_bytes() == b"{}"


@pytest.mark.parametrize("aliased", [False, True])
def test_c3_same_resolved_file_is_not_written(tmp_path, aliased):
    # Rewriting identical bytes (or comparing only lexical paths) still touches the source mtime.
    prior = tmp_path / "prior"
    target = prior / ".." / prior.name if aliased else prior
    tile = _ref(prior, "first", b"{}")
    source = prior / tile["path"]
    os.utime(source, (1_000_000_000, 1_000_000_000))
    mtime = source.stat().st_mtime_ns

    assert copy_previous_history([{"tiles": [tile]}], prior, target) == [tile["path"]]
    assert (source.read_bytes(), source.stat().st_mtime_ns) == (b"{}", mtime)


def test_c3_verified_source_replaces_stale_target(tmp_path):
    # Skipping all existing destinations would leave stale bytes in the new run.
    prior, target = tmp_path / "prior", tmp_path / "target"
    tile = _ref(prior, "first", b"{}")
    dest = target / tile["path"]
    dest.parent.mkdir(parents=True)
    dest.write_bytes(b"[]")

    assert copy_previous_history([{"tiles": [tile]}], prior, target) == [tile["path"]]
    assert dest.read_bytes() == b"{}"
