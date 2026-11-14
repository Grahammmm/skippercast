"""validate_consumer requires the same exact-integer window form as BatchOwner.create."""
import hashlib
import time
from unittest import mock

import pytest

from skippercast.coastal.authenticated_v1 import source_reuse as sr
from skippercast.coastal.budget import Budget, Limits

RAW = b"SYNTHETIC_SOURCE_ONLY"
TOKEN = "a" * 32
TOKEN2 = "c" * 32


class IntSub(int):
    pass


@pytest.fixture
def lifecycle(tmp_path):
    source = tmp_path / "source.bin"
    source.write_bytes(RAW)
    grant = dict(source_reuse_contract=sr.CONTRACT, source_root=str(tmp_path), source_relative_path=source.name,
                 source=dict(path=source.name, sha256=hashlib.sha256(RAW).hexdigest(), bytes=len(RAW)),
                 window_set=[[0, 0, 1, 1], [4, 4, 128, 128]])
    budget = Budget.create(tmp_path / "source-budget.json", Limits(wall_s=60, bytes=len(RAW)))
    runtime = Budget.create(tmp_path / "runtime-budget.json", Limits(wall_s=60))
    owner = sr.BatchOwner.create(tmp_path / "owner.json", grant, budget, runtime_budget=runtime,
                                 deadline_monotonic=time.monotonic() + 30)
    try:
        yield owner, owner.lease(0, "acquire", TOKEN), owner.lease(1, "acquire", TOKEN2)
    finally:
        owner.close()


def call(owner, cert, window, **kw):
    args = dict(expected_grant_sha=cert["grant_sha"], window=window, stage="acquire", token=TOKEN)
    args.update(kw)
    return sr.validate_consumer(owner.fd, cert, **args)


def test_canonical_integer_windows_verify(lifecycle):
    owner, small, big = lifecycle
    for cert, window, tok in ((small, [0, 0, 1, 1], TOKEN), (big, [4, 4, 128, 128], TOKEN2)):
        result = call(owner, cert, window, token=tok)
        assert result["original_source_bytes_read"] == 0
        assert result["sealed_snapshot_bytes_hashed"] == len(RAW)
        assert result["scientific_acceptance"] is False
        assert result["source"]["bytes"] == len(RAW)


BAD = [
    [False, False, True, True], [0, False, 1, 1], [0, 0, True, 1], [0, 0, 1, True],
    [0.0, 0.0, 1.0, 1.0], [0.0, 0, 1, 1], [0, 0, 1.0, 1], [0, 0, 1, 1.0],
    [IntSub(0), 0, 1, 1], [0, 0, IntSub(1), IntSub(1)],
    None, "0011", {"a": 1}, (0, 0, 1, 1), [0, 0, 1], [0, 0, 1, 1, 1], [], [None, 0, 1, 1], ["0", 0, 1, 1],
    [0.5, 0, 1, 1], [float("nan"), 0, 1, 1], [float("inf"), 0, 1, 1],
    [-1, 0, 1, 1], [0, -1, 1, 1], [0, 0, 0, 0], [0, 0, -1, -1], [0, 0, 1, 2], [0, 0, 129, 129],
]


@pytest.mark.parametrize("window", BAD, ids=repr)
def test_malformed_window_refused_before_any_io(lifecycle, window):
    owner, small, _ = lifecycle
    before = owner.path.read_bytes()
    with mock.patch.object(sr, "_load", side_effect=AssertionError("io")) as load, \
         mock.patch.object(sr, "_hash_fd", side_effect=AssertionError("io")) as hashed:
        with pytest.raises(ValueError, match="consumer window/stage/lease fenced"):
            call(owner, small, window)
    assert not load.called and not hashed.called
    assert owner.path.read_bytes() == before
    assert owner.fd >= 0


def test_other_well_formed_window_still_fenced(lifecycle):
    owner, small, _ = lifecycle
    with pytest.raises(ValueError, match="consumer window/stage/lease fenced"):
        call(owner, small, [2, 2, 1, 1])


def test_existing_fences_remain(lifecycle):
    owner, small, _ = lifecycle
    with pytest.raises(ValueError):
        call(owner, small, [0, 0, 1, 1], token="b" * 32)
    with pytest.raises(ValueError):
        call(owner, small, [0, 0, 1, 1], stage="other")
    with pytest.raises(ValueError):
        call(owner, small, [0, 0, 1, 1], expected_grant_sha="0" * 64)
    assert call(owner, small, [0, 0, 1, 1])["scientific_acceptance"] is False
