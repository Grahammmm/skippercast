"""MarineCadastre timestamps: a submillisecond fix stays in the millisecond (and UTC day) that contains it.

Synthetic CSV rows with invented ``999xxxxxx`` identities; the expected epoch milliseconds are written out
independently of the parser. The history case is served by ``http.FakeSession`` (no socket).
"""

from datetime import date

import zstandard

from skippercast.fleet.ais.sources.base import AisPosition, AisStatic
from skippercast.fleet.ais.sources.marinecadastre import MarineCadastreSource, day_url, parse_rows
from skippercast.http import FakeSession

DAY = date(2026, 6, 20)
DAY_START = 1_781_913_600_000          # 2026-06-20T00:00:00Z
DAY_LAST = 1_781_999_999_999           # 2026-06-20T23:59:59.999Z
FOUR_PM = 1_781_971_200_000            # 2026-06-20T16:00:00Z
BBOX = ((9.0, -151.0), (11.0, -149.0))
MMSI = 999_000_111
HEADER = "mmsi,base_date_time,longitude,latitude,vessel_name,call_sign,vessel_type,length,width,transceiver"


def line(when, mmsi=MMSI, name="", cls=""):
    return f"{mmsi},{when},-150.0,10.0,{name},,,,,{cls}"


def parse(times, day=DAY):
    counts = {}
    records = list(parse_rows([HEADER, *(line(t) for t in times)], day, BBOX, counts=counts))
    return [r.ts for r in records], counts


def tally(counts):
    return counts["positions"], counts["other_day"], counts["malformed"]


def test_utc_day_edges_do_not_round_across_midnight():
    cases = [("2026-06-19T23:59:59.999999", None), ("2026-06-20T00:00:00", DAY_START),
             ("2026-06-20T23:59:59.999000", DAY_LAST), ("2026-06-20T23:59:59.999499", DAY_LAST),
             ("2026-06-20T23:59:59.999500", DAY_LAST), ("2026-06-20T23:59:59.999999", DAY_LAST),
             ("2026-06-21T00:00:00", None)]
    for text, expected in cases:
        ts, counts = parse([text])
        assert ts == ([] if expected is None else [expected]), text
        assert tally(counts) == ((0, 1, 0) if expected is None else (1, 0, 0)), text
    ts, counts = parse([text for text, _ in cases])
    assert ts == [DAY_START] + [DAY_LAST] * 4
    assert tally(counts) == (5, 2, 0)


def test_ordinary_submillisecond_floor_is_exact():
    times = ["2026-06-20T16:00:00.123000", "2026-06-20T16:00:00.123001", "2026-06-20T16:00:00.123499",
             "2026-06-20T16:00:00.123500", "2026-06-20T16:00:00.123999", "2026-06-20T16:00:00.124000",
             "2026-06-20 16:00:00", "2026-06-20T16:00:01.500"]
    ts, counts = parse(times)
    assert ts == [FOUR_PM + 123] * 5 + [FOUR_PM + 124, FOUR_PM, FOUR_PM + 1_500]
    assert tally(counts) == (8, 0, 0)


def test_equivalent_offsets_and_naive_utc_agree():
    last = ["2026-06-20T23:59:59.999999Z", " 2026-06-20 23:59:59.999999 ", "2026-06-21T06:59:59.999999+07:00",
            "2026-06-20T23:59:59.999999+00:00"]
    ts, counts = parse(last)
    assert ts == [DAY_LAST] * 4
    assert tally(counts) == (4, 0, 0)
    before = ["2026-06-19T23:59:59.999999Z", "2026-06-19 23:59:59.999999", "2026-06-20T06:59:59.999999+07:00"]
    ts, counts = parse(before)
    assert ts == []
    assert tally(counts) == (0, 3, 0)
    ts, _ = parse(["2026-06-20T09:00:00.000250-07:00"])
    assert ts == [FOUR_PM]


def test_negative_epoch_floor_not_truncation():
    ts, counts = parse(["1969-12-31T23:59:59.999999", "1969-12-31T23:59:59.998", "1970-01-01T00:00:00"],
                       day=date(1969, 12, 31))
    assert ts == [-1, -2]
    assert tally(counts) == (2, 1, 0)
    ts, counts = parse(["1969-12-31T23:59:59.999999", "1970-01-01T00:00:00", "1970-01-01T00:00:00.000999"],
                       day=date(1970, 1, 1))
    assert ts == [0, 0]
    assert tally(counts) == (2, 1, 0)


def test_position_and_static_share_corrected_time():
    rows = [line("2026-06-20T23:59:59.999999", name="TEST BOAT ONE", cls="A"),
            line("2026-06-20T23:59:59.999700", name="TEST BOAT ONE", cls="A"),
            line("2026-06-20T12:00:00.000400", mmsi=999_000_222, name="TEST BOAT TWO", cls="B")]
    counts = {}
    records = list(parse_rows([HEADER, *rows], DAY, BBOX, counts=counts))
    assert [type(r) for r in records] == [AisPosition, AisStatic, AisPosition, AisPosition, AisStatic]
    first, static, again, other, other_static = records
    assert (first.ts, first.received_at, static.ts) == (DAY_LAST, DAY_LAST, DAY_LAST)
    assert (again.ts, again.received_at) == (DAY_LAST, DAY_LAST)
    assert (other.mmsi, other.ts, other.received_at, other_static.ts) == (999_000_222, DAY_START + 43_200_000,
                                                                         DAY_START + 43_200_000,
                                                                         DAY_START + 43_200_000)
    assert static.name == "TEST BOAT ONE" and other_static.ais_class == "B"
    assert {r.source for r in records} == {"marinecadastre"}
    assert {r.msg_type for r in records if isinstance(r, AisPosition)} == {"csv"}
    assert (counts["rows"], counts["positions"], counts["statics"], counts["other_day"]) == (3, 3, 2, 0)


def test_fake_history_keeps_only_the_requested_day(tmp_path):
    rows = [line("2026-06-19T23:59:59.999999"), line("2026-06-20T00:00:00.000001"),
            line("2026-06-20T23:59:59.999999"), line("2026-06-21T00:00:00"),
            line("2026-06-21T00:00:00.000001")]
    body = zstandard.ZstdCompressor(level=3).compress(("\n".join([HEADER, *rows]) + "\n").encode())
    fake = FakeSession({day_url(DAY): body})
    work = tmp_path / "work"
    counts = {}
    records = list(MarineCadastreSource(session=fake, workdir=work).history(DAY, BBOX, {MMSI}, counts=counts))
    assert [(r.mmsi, r.ts) for r in records] == [(MMSI, DAY_START), (MMSI, DAY_LAST)]
    assert (counts["rows"], counts["positions"], counts["other_day"], counts["malformed"]) == (5, 2, 3, 0)
    assert len(fake.calls) == 1
    assert list(work.iterdir()) == []
