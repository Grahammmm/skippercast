"""Governed live discovery: allowlist, caps, dry run and an offline live run.

Synthetic responses only. Requests go through the real bounded script's
`request`/`fetch` with an injected opener, so no socket is opened.
"""
import hashlib
import io
import json
import os
from pathlib import Path

import pytest

from skippercast.coastal import live_discovery as ld
from skippercast.http import Allowlist

HOST = "data.ngdc.noaa.gov"
BASE = f"https://{HOST}/platforms/ocean/nos/coast/H10001-H12000/H11952/"


def plan(**changes):
    value = dict(schema=ld.PLAN, region="synthetic-region", bbox=[-120.65, 34.44, -120.46, 34.56],
                 source_revision="synthetic-source-1", policy_revision="synthetic-policy-1",
                 byte_limit=ld.MAX_BYTES,
                 catalogs=[dict(id="ncei", publisher="NOAA NCEI", authority_url=BASE, allowed_hosts=[HOST],
                                queries=[dict(url=BASE + "BAG/", purpose="metadata", max_bytes=1_000_000,
                                              adapter="listing"),
                                         dict(url=BASE + "footprints.json", purpose="footprint",
                                              max_bytes=1_000_000, adapter="arcgis")])])
    value.update(changes)
    return value


class Reply(io.BytesIO):
    def __init__(self, body, status=200):
        super().__init__(body)
        self.status = status
        self.headers = {"Content-Length": str(len(body))}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


class Opener:
    def __init__(self, bodies):
        self.bodies, self.urls = bodies, []

    def open(self, request, timeout):
        self.urls.append(request.full_url)
        return Reply(self.bodies[request.full_url])


LISTING = (f'<a href="H11952_MB_2m_MLLW_1of1.bag">bag</a> <a href="../DR/">dr</a> '
           f'<a href="https://evil.example.test/x.bag">offsite</a>').encode()
# The fixture CRS must be one discover.known_crs accepts without pyproj: core CI
# runs with no GIS packages, where only CRS84/EPSG:4326/EPSG:3857 are known.
ARCGIS = json.dumps(dict(spatialReference=dict(wkid=4326), features=[dict(
    attributes=dict(NCEI_ID="H11952-bag", SURVEY_ID="H11952", crs="EPSG:4326",
                    DOWNLOAD_URL=BASE + "BAG/H11952_MB_2m_MLLW_1of1.bag"),
    geometry=dict(xmin=-120.6, ymin=34.45, xmax=-120.5, ymax=34.55))])).encode()


def runner_for(opener):
    discover, _ = ld.load_script()
    return lambda url, cap, seconds, body, result: discover.fetch(url, cap, seconds, body, result, opener=opener)


def test_allowlist_requires_exact_reviewed_hosts():
    script_plan, decisions = ld.check_plan(plan())
    assert decisions["hosts"] == {HOST: True} and decisions["planned_max_bytes"] == 2_000_000
    assert "adapter" in script_plan["catalogs"][0]["queries"][0]
    for host in ("gis.ngdc.noaa.gov", "data.ngdc.noaa.gov.evil.test", "DATA.NGDC.NOAA.GOV", "*.noaa.gov"):
        bad = plan()
        bad["catalogs"][0]["allowed_hosts"] = [host]
        with pytest.raises(ValueError):
            ld.check_plan(bad)
    # A suffix wildcard in the repository list never admits a host to a plan.
    with pytest.raises(ValueError, match="allowlist"):
        ld.check_plan(plan(), Allowlist(["*.ngdc.noaa.gov"]))
    offsite = plan()
    offsite["catalogs"][0]["queries"][0]["url"] = "https://www.ncei.noaa.gov/x"
    with pytest.raises(ValueError, match="outside"):
        ld.check_plan(offsite)
    insecure = plan()
    insecure["catalogs"][0]["queries"][0]["url"] = "http://" + HOST + "/x"
    with pytest.raises(ValueError, match="outside"):
        ld.check_plan(insecure)


def test_caps_are_fixed_before_any_request():
    for bad in (dict(byte_limit=ld.MAX_BYTES + 1), dict(byte_limit=0), dict(byte_limit=1.5e6),
                dict(wall_seconds=3600), dict(profile="acquisition60"), dict(byte_limit=1_500_000)):
        with pytest.raises(ValueError):
            ld.check_plan(plan(**bad))
    adapter = plan()
    adapter["catalogs"][0]["queries"][0]["adapter"] = "html-guess"
    with pytest.raises(ValueError, match="adapter"):
        ld.check_plan(adapter)


def test_dry_run_proves_caps_through_script_without_network(tmp_path, monkeypatch):
    discover, _ = ld.load_script()
    monkeypatch.setattr(discover.urllib.request, "build_opener",
                        lambda *a: pytest.fail("dry run must not build a network opener"))
    receipt = ld.dry_run(plan(), tmp_path / "dry")
    assert receipt["network_requests"] == 0
    assert receipt["caps"]["byte_limit"] == 250_000_000 == receipt["caps"]["max_bytes"]
    assert receipt["caps"]["wall_seconds"] == 1800 and receipt["caps"]["discovery_seconds"] == 1500
    assert [s["url"] for s in receipt["schedule"]] == [BASE + "BAG/", BASE + "footprints.json"]
    saved = json.loads((tmp_path / "dry" / "dry-run-receipt.json").read_text())
    assert saved["plan_sha256"] == receipt["plan_sha256"]
    assert not os.stat(tmp_path / "dry" / "dry-run-receipt.json").st_mode & 0o222
    with pytest.raises(ValueError, match="never reused"):
        ld.dry_run(plan(), tmp_path / "dry")


def test_live_run_freezes_catalog_diff_and_receipt(tmp_path):
    opener = Opener({BASE + "BAG/": LISTING, BASE + "footprints.json": ARCGIS})
    previous = dict(schema=ld.CATALOG, candidates=[dict(source_id="ncei:retired", access_url=None)])
    (tmp_path / "previous.json").write_text(json.dumps(previous))
    receipt = ld.run(plan(), tmp_path / "live", previous=tmp_path / "previous.json",
                     runner=runner_for(opener))
    assert opener.urls == [BASE + "BAG/", BASE + "footprints.json"]
    out = tmp_path / "live"
    catalog = json.loads((out / "catalog.json").read_text())
    change = json.loads((out / "catalog-diff.json").read_text())
    ids = [c["source_id"] for c in catalog["candidates"]]
    assert ids == ["ncei:H11952-bag", "ncei:H11952_MB_2m_MLLW_1of1.bag"]
    listed = catalog["candidates"][1]
    # A file name is not a footprint: the listing lead stays blocked and unknown.
    assert listed["extent"]["bbox"] is None and "unknown_or_non_geographic_bbox_crs" in listed["rejection_reasons"]
    assert listed["access_url"] == BASE + "BAG/H11952_MB_2m_MLLW_1of1.bag"
    assert catalog["usable_source_ids"] == ["ncei:H11952-bag"]
    assert all(c["terrain"]["accepted"] is False for c in catalog["candidates"])
    assert catalog["mapping_accepted"] is False and catalog["review_required"] is True
    assert change["added"] == ids and change["removed"] == ["ncei:retired"]
    assert receipt["within_caps"] and receipt["network_requests"] == 2
    assert receipt["budget_charged_bytes"] == len(LISTING) + len(ARCGIS) == receipt["observed_body_bytes"]
    assert {o["path"] for o in receipt["outputs"]} == {"catalog.json", "catalog-diff.json", "receipt.json"}
    for name in ("catalog.json", "catalog-diff.json", "receipt.json"):
        assert not os.stat(out / name).st_mode & 0o222
    assert receipt["catalog_id"] == catalog["catalog_id"]
    with pytest.raises(ValueError, match="never reused"):
        ld.run(plan(), out, runner=runner_for(opener))


def test_second_run_diff_reports_unchanged_and_changed(tmp_path):
    opener = Opener({BASE + "BAG/": LISTING, BASE + "footprints.json": ARCGIS})
    ld.run(plan(), tmp_path / "one", runner=runner_for(opener))
    moved = json.loads(ARCGIS)
    moved["features"][0]["attributes"]["crs"] = "EPSG:3857"
    opener2 = Opener({BASE + "BAG/": LISTING, BASE + "footprints.json": json.dumps(moved).encode()})
    receipt = ld.run(plan(), tmp_path / "two", previous=tmp_path / "one" / "catalog.json",
                     runner=runner_for(opener2))
    change = json.loads((tmp_path / "two" / "catalog-diff.json").read_text())
    assert change["added"] == [] and change["removed"] == [] and change["unchanged"] == 1
    assert change["changed"] == [dict(source_id="ncei:H11952-bag", fields=["metadata"])]
    assert receipt["diff_summary"] == dict(added=0, removed=0, changed=1, unchanged=1)


def test_access_stop_and_cutoff_skip_without_spending(tmp_path):
    class Denied:
        urls = []

        def open(self, request, timeout):
            self.urls.append(request.full_url)
            import urllib.error
            raise urllib.error.HTTPError(request.full_url, 403, "Forbidden", {}, None)

    opener = Denied()
    receipt = ld.run(plan(), tmp_path / "denied", runner=runner_for(opener))
    assert opener.urls == [BASE + "BAG/"]
    assert [e["action"] for e in receipt["events"]] == ["requested", "skipped"]
    assert receipt["budget_charged_bytes"] == 0
    ticks = iter([0.0] + [ld.WALL_SECONDS] * 50)
    late = ld.run(plan(), tmp_path / "late", runner=runner_for(Opener({})), monotonic=lambda: next(ticks))
    assert late["network_requests"] == 0
    assert [e["reason"] for e in late["events"]] == ["discovery_cutoff", "discovery_cutoff"]
    catalog = json.loads((tmp_path / "late" / "catalog.json").read_text())
    assert catalog["bounded_plan_finished"] is False and len(catalog["unattempted_queries"]) == 2


def test_coordinator_discover_stage_is_unchanged():
    source = (Path(ld.__file__).parent / "stage_cli.py").read_text()
    assert "coastal-local-discovery-plan-v1" in source and ld.CATALOG not in source


# PC-2: a THREDDS dataset page on www.ngdc.noaa.gov (NOAA CRM). Synthetic body.
THREDDS = "www.ngdc.noaa.gov"
CRM = "crm_socal_1as_vers2.nc"
THREDDS_PAGE = f"https://{THREDDS}/thredds/catalog/crm/catalog.html?dataset=crmDatasets/{CRM}"
FILE_SERVER = f"https://{THREDDS}/thredds/fileServer/crm/{CRM}"
THREDDS_LISTING = "\n".join(f'<a href="{href}">x</a>' for href in (
    f"/thredds/dodsC/crm/{CRM}",                       # OPeNDAP service, not a file
    f"/thredds/dodsC/crm/{CRM}.html",
    f"/thredds/fileServer/crm/{CRM}",                  # HTTPServer: the plain file
    f"/thredds/ncss/crm/{CRM}",                        # NetcdfSubset service
    f"/thredds/ncss/grid/crm/{CRM}/dataset.html",
    f"/thredds/wcs/crm/{CRM}?service=WCS&version=1.0.0&request=GetCapabilities",
    f"/thredds/iso/crm/{CRM}?catalog=x&dataset=y",
    "/thredds/fileServer/",                            # no file name
    f"catalog.html?dataset=crmDatasets/{CRM}",
    "/mgg/coastal/crm_vol6.nc",                        # plain directory file, not THREDDS
    "https://evil.example.test/thredds/fileServer/crm/x.nc",
    "/thredds/fileServer/crm/crm_socal_1as_vers2.tif",
)).encode()


def thredds_plan():
    return plan(region="coast-c1-morro-bay-synthetic", bbox=[-121.95, 34.95, -120.55, 35.85],
                catalogs=[dict(id="ngdc-thredds", publisher="NOAA NCEI", authority_url=THREDDS_PAGE,
                               allowed_hosts=[THREDDS],
                               queries=[dict(url=THREDDS_PAGE, purpose="metadata", max_bytes=1_000_000,
                                             adapter="listing")])])


def test_thredds_listing_keeps_only_plain_netcdf_file_links(tmp_path):
    discover, _ = ld.load_script()
    body = tmp_path / "listing.html"
    body.write_bytes(THREDDS_LISTING)
    row = dict(body_path=str(body), url=discover.url_key(THREDDS_PAGE), sha256="0" * 64)
    found = ld.listing_annotation(discover, row, [THREDDS])
    urls = {c["publisher_id"]: c["access_url"] for c in found["candidates"]}
    assert urls == {CRM: FILE_SERVER, "crm_vol6.nc": f"https://{THREDDS}/mgg/coastal/crm_vol6.nc",
                    "crm_socal_1as_vers2.tif": f"https://{THREDDS}/thredds/fileServer/crm/crm_socal_1as_vers2.tif"}
    assert all(c["bbox"] is None and c["vertical_datum"] is None for c in found["candidates"])
    # The pre-existing suffixes are unchanged; .nc is the only addition.
    assert ld.LISTING_SUFFIXES == (".bag", ".bag.gz", ".tif", ".tiff", ".zip", ".xml", ".nc")


def test_thredds_listing_dry_run_receipt_without_network(tmp_path, monkeypatch):
    discover, _ = ld.load_script()
    monkeypatch.setattr(discover.urllib.request, "build_opener",
                        lambda *a: pytest.fail("dry run must not build a network opener"))
    receipt = ld.dry_run(thredds_plan(), tmp_path / "dry")
    assert receipt["network_requests"] == 0
    assert receipt["allowlist"]["hosts"] == {THREDDS: True}
    assert receipt["caps"]["byte_limit"] == ld.MAX_BYTES and receipt["caps"]["wall_seconds"] == ld.WALL_SECONDS
    assert [(s["adapter"], s["max_bytes"]) for s in receipt["schedule"]] == [("listing", 1_000_000)]
    saved = (tmp_path / "dry" / "dry-run-receipt.json").read_bytes()
    assert json.loads(saved)["plan_sha256"] == receipt["plan_sha256"]
    assert receipt["output"]["sha256"] == hashlib.sha256(saved).hexdigest()


def test_thredds_listing_run_freezes_netcdf_entry_offline(tmp_path):
    discover, _ = ld.load_script()
    opener = Opener({discover.url_key(THREDDS_PAGE): THREDDS_LISTING})
    receipt = ld.run(thredds_plan(), tmp_path / "live", runner=runner_for(opener))
    catalog = json.loads((tmp_path / "live" / "catalog.json").read_text())
    rows = {c["publisher_id"]: c for c in catalog["candidates"]}
    assert rows[CRM]["access_url"] == FILE_SERVER
    assert rows[CRM]["source_id"] == f"ngdc-thredds:{CRM}"
    assert not any("/dodsC/" in c["access_url"] or "/ncss/" in c["access_url"] for c in rows.values())
    assert receipt["within_caps"] and receipt["network_requests"] == 1
    assert receipt["budget_charged_bytes"] == len(THREDDS_LISTING)
    assert catalog["mapping_accepted"] is False and catalog["review_required"] is True
    assert all(len(o["sha256"]) == 64 for o in receipt["outputs"])
