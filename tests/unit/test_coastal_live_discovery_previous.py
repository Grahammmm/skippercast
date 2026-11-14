"""Bounded previous-catalog read in live discovery (offline, synthetic files)."""

from __future__ import annotations

import hashlib
import json
import socket
from pathlib import Path

import pytest

from skippercast.coastal import live_discovery as ld
from tests.unit.test_coastal_live_discovery import ARCGIS, BASE, LISTING, Opener, plan, runner_for

CAP = ld.load_script()[0].MAX_METADATA


class Stop(Exception):
    pass


class Probe:
    """Forwarding wrapper around the real binary stream for one target path."""

    def __init__(self, monkeypatch, target, before_read=None):
        self.target, self.reads, self.opened, self.closed = Path(target), [], 0, 0
        self.before_read = before_read
        real_open = Path.open
        probe = self

        class Stream:
            def __init__(self, fh):
                self.fh = fh

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                probe.closed += 1
                self.fh.close()

            def read(self, size=-1):
                if probe.before_read:
                    probe.before_read()
                data = self.fh.read(size)
                probe.reads.append((size, len(data)))
                return data

        def patched(path, *args, **kwargs):
            fh = real_open(path, *args, **kwargs)
            if Path(path) == probe.target:
                probe.opened += 1
                return Stream(fh)
            return fh

        monkeypatch.setattr(Path, "open", patched)


def padded(total, extra=None):
    body = json.dumps(dict(schema=ld.CATALOG, candidates=[]))
    return (body + " " * (total - len(body))).encode()


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def deny(*a, **k):
        raise AssertionError("socket use is forbidden")

    monkeypatch.setattr(socket.socket, "connect", deny)


def refuses_before_side_effects(monkeypatch, tmp_path, previous):
    monkeypatch.setattr(ld, "_create", lambda out: pytest.fail("output must not be created"))
    with pytest.raises(ValueError, match="previous catalog exceeds metadata limit"):
        ld.run(plan(), tmp_path / "live", previous=previous,
               runner=lambda *a: pytest.fail("no request"))
    assert not (tmp_path / "live").exists()


def test_oversized_previous_reads_only_cap_plus_one(tmp_path, monkeypatch):
    previous = tmp_path / "previous.json"
    data = padded(2 * CAP)
    previous.write_bytes(data)
    probe = Probe(monkeypatch, previous)
    refuses_before_side_effects(monkeypatch, tmp_path, previous)
    assert probe.reads == [(CAP + 1, CAP + 1)]
    assert probe.opened == probe.closed == 1
    assert previous.read_bytes() == data


def test_exact_cap_admitted_cap_plus_one_refused(tmp_path, monkeypatch):
    exact = tmp_path / "exact.json"
    exact.write_bytes(padded(CAP))
    probe = Probe(monkeypatch, exact)
    monkeypatch.setattr(ld, "_create", lambda out: (_ for _ in ()).throw(Stop()))
    with pytest.raises(Stop):
        ld.run(plan(), tmp_path / "live", previous=exact)
    assert probe.reads == [(CAP + 1, CAP)] and probe.closed == 1
    over = tmp_path / "over.json"
    over.write_bytes(padded(CAP + 1))
    refuses_before_side_effects(monkeypatch, tmp_path, over)


def test_growth_before_read_stays_bounded(tmp_path, monkeypatch):
    previous = tmp_path / "grow.json"
    previous.write_bytes(padded(CAP - 10))

    def grow():
        with open(previous, "ab") as fh:
            fh.write(b" " * (CAP + 100))

    probe = Probe(monkeypatch, previous, before_read=grow)
    refuses_before_side_effects(monkeypatch, tmp_path, previous)
    assert probe.reads == [(CAP + 1, CAP + 1)]


@pytest.mark.parametrize("schema_doc", [
    dict(schema=ld.CATALOG, candidates=[dict(source_id="ncei:é retired", access_url=None, note="ü")]),
])
def test_accepted_snapshot_is_hashed_and_opened_once(tmp_path, monkeypatch, schema_doc):
    previous = tmp_path / "previous.json"
    raw = ("\n  " + json.dumps(schema_doc, ensure_ascii=False) + "\n\n").encode()
    previous.write_bytes(raw)
    probe = Probe(monkeypatch, previous)
    opener = Opener({BASE + "BAG/": LISTING, BASE + "footprints.json": ARCGIS})
    receipt = ld.run(plan(), tmp_path / "live", previous=previous, runner=runner_for(opener))
    assert probe.opened == 1 and probe.closed == 1
    change = json.loads((tmp_path / "live" / "catalog-diff.json").read_text())
    assert change["previous"]["sha256"] == hashlib.sha256(raw).hexdigest()
    assert change["previous"]["bytes"] == len(raw)
    assert change["removed"] == ["ncei:é retired"] and len(change["added"]) == 2
    assert receipt["review_required"] is True and receipt["execution_authorized"] is False


def test_malformed_and_missing_previous_keep_refusals(tmp_path, monkeypatch):
    monkeypatch.setattr(ld, "_create", lambda out: pytest.fail("output must not be created"))
    cases = {"empty": b"", "bad": b"{not json", "schema": b'{"schema": "other", "candidates": []}'}
    for name, data in cases.items():
        path = tmp_path / f"{name}.json"
        path.write_bytes(data)
        with pytest.raises((ValueError, KeyError)):
            ld.run(plan(), tmp_path / "live", previous=path)
    with pytest.raises(FileNotFoundError):
        ld.run(plan(), tmp_path / "live", previous=tmp_path / "missing.json")


def test_read_error_closes_stream_and_creates_nothing(tmp_path, monkeypatch):
    previous = tmp_path / "previous.json"
    previous.write_bytes(padded(100))

    def boom():
        raise OSError("injected read failure")

    probe = Probe(monkeypatch, previous, before_read=boom)
    monkeypatch.setattr(ld, "_create", lambda out: pytest.fail("output must not be created"))
    with pytest.raises(OSError, match="injected"):
        ld.run(plan(), tmp_path / "live", previous=previous)
    assert probe.opened == probe.closed == 1


def test_no_previous_opens_no_stream(tmp_path, monkeypatch):
    probe = Probe(monkeypatch, tmp_path / "never.json")
    opener = Opener({BASE + "BAG/": LISTING, BASE + "footprints.json": ARCGIS})
    receipt = ld.run(plan(), tmp_path / "live", runner=runner_for(opener))
    assert probe.opened == 0
    assert receipt["mapping_accepted"] is False and receipt["execution_authorized"] is False
