"""SC45: literal saved HTML, real parser and real offline discovery consumer."""
import hashlib
import json
from pathlib import Path

import pytest

from skippercast.coastal import live_discovery as ld
from tests.unit import test_coastal_live_discovery as original

HOST = original.HOST
BASE = original.BASE
COLLISION = "listing_basename_collision"


def annotation(tmp_path, html):
    body = html.encode()
    path = tmp_path / "listing.html"
    path.write_bytes(body)
    row = dict(body_path=str(path), url=BASE, sha256=hashlib.sha256(body).hexdigest())
    discover, _ = ld.load_script()
    return ld.listing_annotation(discover, row, [HOST])


def links(*hrefs):
    return "".join(f'<a href="{href}">synthetic file</a>' for href in hrefs)


def expected(html, pairs):
    return dict(response_sha256=hashlib.sha256(html.encode()).hexdigest(), candidates=[
        dict(publisher_id=name, title=name, bbox=None, bbox_crs=None, catalog_geometry=None,
             crs=None, resolution=None, vertical_datum=None, z_units=None, rights=None,
             size_bytes=None, source_hash=None, access_url=url, alternate_of=None,
             field_evidence=dict(access_url="literal href in saved directory listing",
                                 publisher_id="file name of that href"))
        for name, url in pairs])


def test_unique_basename_control(tmp_path):
    names = ("z.XML", "b.zip", "a.bag", "d.bag.gz", "e.tif", "f.tiff")
    html = links(*names)
    result = annotation(tmp_path, html)
    assert result == expected(html, [(name, BASE + name) for name in sorted(names)])
    assert annotation(tmp_path, links(*reversed(names)))["candidates"] == result["candidates"]


def test_duplicate_identical_control(tmp_path):
    html = links("grid.bag", "grid.bag", "grid.bag")
    assert annotation(tmp_path, html) == expected(html, [("grid.bag", BASE + "grid.bag")])


@pytest.mark.parametrize("hrefs", [
    ("one/grid.bag", "two/grid.bag"),
    ("two/grid.bag", "one/grid.bag"),
    ("one/grid.bag", "one/grid.bag", "two/grid.bag"),
    ("two/grid.bag", "one/grid.bag", "two/grid.bag"),
])
def test_distinct_paths_collide(tmp_path, hrefs, record_property):
    with pytest.raises(ValueError) as exc:
        annotation(tmp_path, links(*hrefs))
    assert str(exc.value) == COLLISION
    record_property("reason", str(exc.value))


@pytest.mark.parametrize("excluded", [
    "https://offhost.example.test/grid.bag", "other/grid.bag?download=1",
    "other/unsupported.txt", "../directory/",
])
def test_excluded_links_do_not_collide(tmp_path, excluded):
    html = links("grid.bag", excluded)
    assert annotation(tmp_path, html) == expected(html, [("grid.bag", BASE + "grid.bag")])


def test_existing_saved_listing_is_unchanged(tmp_path):
    html = original.LISTING.decode()
    # The historical fixture is passed through its real parser, not a link seam.
    assert annotation(tmp_path, html) == expected(html, [
        ("H11952_MB_2m_MLLW_1of1.bag", BASE + "H11952_MB_2m_MLLW_1of1.bag")])


@pytest.mark.parametrize("reverse", [False, True])
def test_actual_run_records_ingest_failure_and_incomplete_coverage(tmp_path, reverse, record_property):
    paths = ["one/grid.bag", "two/grid.bag"]
    if reverse:
        paths.reverse()
    body = links(*paths).encode()
    opener = original.Opener({BASE + "BAG/": body, BASE + "footprints.json": original.ARCGIS})
    # The existing in-process runner exercises request/fetch/ingest/finalize.
    receipt = ld.run(original.plan(), tmp_path / "consumer", runner=original.runner_for(opener))
    events = receipt["events"]
    assert [e["action"] for e in events] == ["requested", "ingest_failed", "requested", "ingested"]
    assert events[1] == dict(url=BASE + "BAG/", action="ingest_failed", request_id=1, reason=COLLISION)
    catalog = json.loads((tmp_path / "consumer" / "catalog.json").read_text())
    checkpoint = json.loads((tmp_path / "consumer" / "checkpoint.json").read_text())
    assert catalog["discovery_complete"] is False
    assert catalog["bounded_plan_finished"] is True
    assert not checkpoint["requests"][0].get("ingested", False)
    assert [c["source_id"] for c in catalog["candidates"]] == ["ncei:H11952-bag"]
    assert receipt["review_required"] is True and receipt["mapping_accepted"] is False
    assert opener.urls == [BASE + "BAG/", BASE + "footprints.json"]
    assert not (tmp_path / "consumer" / "annotation-001.json").exists()
    record_property("events", json.dumps(events, sort_keys=True))
    record_property("discovery_complete", catalog["discovery_complete"])


def test_access_stop_still_skips_following_query(tmp_path, record_property):
    import urllib.error

    class Denied:
        def __init__(self):
            self.urls = []

        def open(self, request, timeout):
            self.urls.append(request.full_url)
            raise urllib.error.HTTPError(request.full_url, 403, "Forbidden", {}, None)

    denied = Denied()
    receipt = ld.run(original.plan(), tmp_path / "denied", runner=original.runner_for(denied))
    assert denied.urls == [BASE + "BAG/"]
    assert [e["action"] for e in receipt["events"]] == ["requested", "skipped"]
    assert receipt["events"][0]["status"] == "ACCESS_STOP"
    assert receipt["events"][1]["reason"] == "catalog_access_stop"
    assert receipt["budget_charged_bytes"] == 0
    catalog = json.loads((tmp_path / "denied" / "catalog.json").read_text())
    assert catalog["discovery_complete"] is False
    assert catalog["bounded_plan_finished"] is False
    assert catalog["unattempted_queries"] == [BASE + "footprints.json"]
    record_property("events", json.dumps(receipt["events"], sort_keys=True))
    record_property("discovery_complete", catalog["discovery_complete"])


def test_candidate_origin():
    root = Path(original.__file__).resolve().parents[2]
    assert Path(ld.__file__).resolve() == root / "src/skippercast/coastal/live_discovery.py"
    discover, path = ld.load_script()
    assert path.resolve() == root / ld.SCRIPT
    assert Path(discover.__file__).resolve() == path.resolve()
