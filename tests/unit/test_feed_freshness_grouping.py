"""Whole-output regressions for dated feed-health advisory lines (C1–C4)."""
from datetime import datetime, timezone
import json

import pytest

from scripts import check_feed_freshness as freshness


BUILT = "2026-11-19T00:00:00Z"
DATES = ("2026-10-27", "2026-10-28", "2026-10-29")


def dated(prefix, dates=DATES, **fields):
    return {f"{prefix}-{date}": {"kind": "charter-reports", "status": "failed", **fields} for date in dates}


def daily(sources, critical_kinds=()):
    return freshness.source_verdict({"generated_at": BUILT, "sources": sources}, 12, "Daily", critical_kinds)


@pytest.mark.parametrize("include_oct_30", [True, False])
def test_c1_backup_never_counts_toward_a_fold(include_oct_30):
    # An interleaved backup must neither disappear nor supply the third date.
    ordinary = ("2026-10-29", "2026-10-27")
    sources = dated("catches", ordinary + (("2026-10-30",) if include_oct_30 else ()))
    sources.update(dated("catches", ("2026-10-28",), station="backup-station", fallback_for="primary-station"))
    backup = ("- warn catches-2026-10-28 (charter-reports): failed, backup backup-station for primary-station "
              "(degraded service), no data time (advisory)")
    if include_oct_30:
        expected = ["Daily: 4 degraded source(s), none critical past 12 h.",
                    "- warn catches-* (charter-reports): failed, no data time (advisory): 3 dated files, "
                    "2026-10-27 to 2026-10-30: 2026-10-27, 2026-10-29, 2026-10-30", backup]
    else:
        expected = ["Daily: 3 degraded source(s), none critical past 12 h.",
                    "- warn catches-2026-10-27 (charter-reports): failed, no data time (advisory)", backup,
                    "- warn catches-2026-10-29 (charter-reports): failed, no data time (advisory)"]
    assert daily(sources, critical_kinds=[]) == (0, expected)


def test_c1_prefix_kind_and_status_keep_independent_groups():
    # Grouping by date shape alone would combine different series or hide changed diagnoses.
    sources = {**dated("landings"), **dated("catches"),
               **dated("catches", ("2026-10-30",), status="stale"),
               **dated("catches", ("2026-10-31",), kind="page-watch")}
    assert daily(sources) == (0, [
        "Daily: 8 degraded source(s), none critical past 12 h.",
        "- warn catches-* (charter-reports): failed, no data time (advisory): 3 dated files, "
        "2026-10-27 to 2026-10-29: 2026-10-27, 2026-10-28, 2026-10-29",
        "- warn catches-2026-10-30 (charter-reports): stale, no data time (advisory)",
        "- warn catches-2026-10-31 (page-watch): failed, no data time (advisory)",
        "- warn landings-* (charter-reports): failed, no data time (advisory): 3 dated files, "
        "2026-10-27 to 2026-10-29: 2026-10-27, 2026-10-28, 2026-10-29",
    ])


def test_c2_critical_outages_keep_individual_fail_and_over_lines():
    # With and without a healthy sibling, no dated critical diagnosis may be hidden.
    failed = dated("buoy", kind="observation")
    assert daily(failed, ["observation"]) == (2, [
        "Daily: every observation source degraded past 12 h.",
        *[f"- FAIL buoy-{date} (observation): failed, no data time (critical, limit 12 h)" for date in DATES],
    ])
    with_healthy = {**failed, "buoy-healthy": {"kind": "observation", "status": "ok"}}
    assert daily(with_healthy, ["observation"]) == (4, [
        "Daily: 3 critical source(s) degraded past 12 h while others of the same kind are not "
        "(partial outage; reported, does not fail).",
        *[f"- over buoy-{date} (observation): failed, no data time (critical, limit 12 h)" for date in DATES],
    ])


def test_c2_dated_rows_with_data_and_non_suffix_ids_keep_original_lines():
    # Three retained rows have an age; three other IDs contain dates but not as a suffix.
    retained = dated("chlorophyll", kind="chlorophyll", status="retained", last_success_at="2026-11-18T18:00:00Z")
    summaries = {f"catches-{date}-summary": {"kind": "charter-reports", "status": "failed"} for date in DATES}
    assert daily({**retained, **summaries}) == (0, [
        "Daily: 6 degraded source(s), none critical past 12 h.",
        *[f"- warn catches-{date}-summary (charter-reports): failed, no data time (advisory)" for date in DATES],
        *[f"- warn chlorophyll-{date} (chlorophyll): retained, data 6.0 h old (advisory)" for date in DATES],
    ])


def test_c3_report_exit_and_stale_event_survive_a_fold(tmp_path, monkeypatch, capsys):
    # Exercise the real --report path: stale and failing daily feed, partial live outage.
    live = {"published_at": "2026-11-21T00:00:00Z", "sources": {
        "buoy-ok": {"kind": "observation", "status": "ok"},
        "buoy-out": {"kind": "observation", "status": "failed"},
    }}
    data = {"published_at": BUILT, "sources": {
        **dated("catches"),
        "alerts": {"kind": "advisory", "status": "failed"},
        **{kind: {"kind": kind, "status": "ok"} for kind in ("forecast", "observation", "prediction")},
    }, "health": {"degraded_reasons": ["satellite section withheld", "coverage incomplete"]}}
    base = "https://site.example"
    feeds = {
        f"{base}/feeds/conditions/latest.json": live,
        freshness.FEED: live,
        f"{base}/feeds/data/latest.json": data,
        freshness.RAW + "data/latest.json": data,
    }
    monkeypatch.setattr(freshness, "published_regions", lambda _: [])
    report = tmp_path / "report.json"
    with pytest.raises(SystemExit) as exited:
        freshness.main(["--public-base", base, "--report", str(report)], feeds.__getitem__,
                       datetime(2026, 11, 21, tzinfo=timezone.utc))
    assert (type(exited.value), exited.value.code, str(exited.value)) == (SystemExit, 3, "3")
    assert json.loads(report.read_text()) == {
        "stale": True, "degraded": True, "partial": True, "stale_feeds": [
            {"feed": "data", "last_published": "2026-11-19T00:00:00Z", "age_hours": 48.0,
             "limit_hours": 36.0, "late_hours": 12.0, "reason": None},
        ],
    }
    assert capsys.readouterr().out.splitlines() == [
        "Public conditions feed (https://site.example/feeds/conditions/latest.json) is fresh: published 0.0 h ago.",
        "GitHub conditions branch is fresh: published 0.0 h ago.",
        "Live conditions feed: 1 critical source(s) degraded past 12 h while others of the same kind are not "
        "(partial outage; reported, does not fail).",
        "- over buoy-out (observation): failed, no data time (critical, limit 12 h)",
        "",
        "Public data feed (https://site.example/feeds/data/latest.json) is stale: last published "
        "2026-11-19T00:00:00Z (48.0 h ago; limit 36 h).",
        "GitHub data branch is stale: last published 2026-11-19T00:00:00Z (48.0 h ago; limit 36 h). (secondary signal)",
        "Daily data feed: every advisory source degraded past 48 h.",
        "- FAIL alerts (advisory): failed, no data time (critical, limit 48 h)",
        "- warn catches-* (charter-reports): failed, no data time (advisory): 3 dated files, "
        "2026-10-27 to 2026-10-29: 2026-10-27, 2026-10-28, 2026-10-29",
        "Daily data feed is degraded by design: satellite section withheld; coverage incomplete.",
    ]


def test_c4_seven_catches_and_retained_chlorophyll():
    # Reproduce the reported shape without live inputs; don't collapse the retained line.
    dates = ("2026-11-02", "2026-11-01", "2026-10-31", "2026-10-30", *reversed(DATES))
    sources = {"chlorophyll": {"kind": "chlorophyll", "status": "retained", "last_success_at": "2026-11-18T18:00:00Z"},
               **dated("catches", dates)}
    assert daily(sources) == (0, [
        "Daily: 8 degraded source(s), none critical past 12 h.",
        "- warn catches-* (charter-reports): failed, no data time (advisory): 7 dated files, 2026-10-27 to 2026-11-02: "
        "2026-10-27, 2026-10-28, 2026-10-29, 2026-10-30, 2026-10-31, 2026-11-01, 2026-11-02",
        "- warn chlorophyll (chlorophyll): retained, data 6.0 h old (advisory)",
    ])


def test_c4_two_dated_rows_stay_unfolded():
    # The threshold is three even in a feed with no other degraded sources.
    assert daily(dated("catches", DATES[:2])) == (0, [
        "Daily: 2 degraded source(s), none critical past 12 h.",
        "- warn catches-2026-10-27 (charter-reports): failed, no data time (advisory)",
        "- warn catches-2026-10-28 (charter-reports): failed, no data time (advisory)",
    ])
