"""A stale private confirmation can be withdrawn, and stays withdrawn when its binding returns (F08-13).

Contract: ``confirm.withdraw`` needs only the exact ledger pair, never the registry. Believable bug: it requires
the registry to hold the pair, so a stale confirmation cannot be revoked and counts again when the old MMSI returns.
"""
from datetime import date
from types import SimpleNamespace

import pytest

from skippercast.fleet import confirm, coverage

VESSEL, OLD, NEW = "a" * 32, "999000001", "999000002"
METHOD = confirm.METHODS[0]
NOW = date(2026, 11, 10)


def held_now(mmsi):
    return lambda: {VESSEL: mmsi}


def confirmed_count(entries, mmsi):
    region = SimpleNamespace(ports=[SimpleNamespace(id="p", region="ca-test")])
    snapshot = SimpleNamespace(vessels=[{"id": VESSEL, "port_id": "p", "status": "active", "mmsi": mmsi}])
    reason = coverage.coverage_status(region, snapshot, entries)["ca-test"]["reason"]
    return int(reason.split("MMSI; ")[1].split(" ")[0])


def stale_ledger(tmp_path):
    """OLD confirmed while the registry held it; the registry now holds NEW (so OLD is stale)."""
    assert confirm.add("CA", "staging", VESSEL, OLD, METHOD, "2026-11-01", "EVID-1", held_now(OLD), var=tmp_path, now=NOW) == 1
    assert confirm.listing(confirm.load_confirmations("CA", "staging", tmp_path), {VESSEL: NEW})[0]["state"] == "stale"


def test_stale_pair_is_withdrawn_without_the_registry_and_stays_withdrawn_when_the_binding_returns(tmp_path):
    stale_ledger(tmp_path)
    before = confirm.load_confirmations("CA", "staging", tmp_path)[0]
    assert confirm.withdraw("CA", "staging", VESSEL, OLD, "2026-11-03", var=tmp_path, now=NOW) == 1
    (entry,) = confirm.load_confirmations("CA", "staging", tmp_path)
    assert entry == {**before, "withdrawn_on": "2026-11-03"}, "only withdrawn_on changes; nothing is rebound or erased"
    assert confirm.withdraw("CA", "staging", VESSEL, OLD, "2026-11-03", var=tmp_path, now=NOW) == 0
    # the old binding returns: the withdrawn evidence must not count again
    assert confirm.listing([entry], {VESSEL: OLD})[0]["state"] == "withdrawn"
    assert confirmed_count([entry], OLD) == 0
    assert confirmed_count([before], OLD) == 1, "positive control: without the withdrawal the returned pair counts"


def test_the_cli_withdraws_a_stale_pair_when_the_registry_cannot_be_read(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("SKIPPERCAST_FLEET_VAR", str(tmp_path))  # no staging registry exists here
    stale_ledger(tmp_path)
    argv = ["withdraw", "--region", "CA", "--vessel-id", VESSEL, "--mmsi", OLD, "--withdrawn-on", "2026-11-03"]
    assert confirm.main(argv) == 0
    assert capsys.readouterr().out == '{"action": "withdraw", "affected": 1}\n'
    assert confirm.load_confirmations("CA", "staging", tmp_path)[0]["withdrawn_on"] == "2026-11-03"


def test_a_held_pair_still_withdraws(tmp_path):
    confirm.add("CA", "staging", VESSEL, OLD, METHOD, "2026-11-01", "EVID-1", held_now(OLD), var=tmp_path, now=NOW)
    assert confirm.withdraw("CA", "staging", VESSEL, OLD, "2026-11-03", var=tmp_path, now=NOW) == 1


def test_only_the_exact_recorded_pair_is_withdrawn_and_refusals_change_nothing(tmp_path):
    stale_ledger(tmp_path)
    path = confirm.ledger_path("CA", "staging", tmp_path)
    before = path.read_bytes()
    for vessel, mmsi, when in ((VESSEL, NEW, "2026-11-03"), ("b" * 32, OLD, "2026-11-03"),
                               (VESSEL, OLD, "2026-10-31"), (VESSEL, OLD, "2026-11-11")):
        with pytest.raises(confirm.ConfirmError):
            confirm.withdraw("CA", "staging", vessel, mmsi, when, var=tmp_path, now=NOW)
    assert path.read_bytes() == before


def test_a_new_confirmation_still_needs_current_ownership(tmp_path):
    stale_ledger(tmp_path)
    confirm.withdraw("CA", "staging", VESSEL, OLD, "2026-11-03", var=tmp_path, now=NOW)
    path = confirm.ledger_path("CA", "staging", tmp_path)
    before = path.read_bytes()
    for mmsi in (OLD, NEW):  # the registry holds neither the withdrawn pair's binding nor a mismatching one
        with pytest.raises(confirm.ConfirmError, match=confirm.NOT_HELD):
            confirm.add("CA", "staging", VESSEL, mmsi, METHOD, "2026-11-05", "EVID-2", held_now("999000003"),
                        var=tmp_path, now=NOW)
    assert path.read_bytes() == before
    # positive control: with current ownership a new confirmation of the new pair is recorded
    assert confirm.add("CA", "staging", VESSEL, NEW, METHOD, "2026-11-05", "EVID-2", held_now(NEW),
                       var=tmp_path, now=NOW) == 1
